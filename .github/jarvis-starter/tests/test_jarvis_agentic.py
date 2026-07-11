from __future__ import annotations

import json

from jarvis import Config, Jarvis


class ScriptedAI:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.enabled = True
        self.calls: list[tuple[str, str]] = []

    def ask(self, prompt: str, memory_context: str = "", instructions: str = "") -> str:
        self.calls.append((prompt, instructions))
        return self.responses.pop(0)

    def status(self) -> str:
        return "scripted-ai-for-tests"


def make_jarvis(tmp_path) -> Jarvis:
    config = Config(assistant_name="Jarvis", confirm_actions=False, sites={}, apps={})
    return Jarvis(config=config, voice=False, data_dir=tmp_path)


def agent_turn(tool_calls, final=""):
    return json.dumps({"thought": "test", "tool_calls": tool_calls, "final": final})


class TestDeduplication:
    def test_duplicate_call_not_re_executed(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI(
            [
                agent_turn([{"tool": "add_note", "args": {"text": "acheter du pain"}}]),
                agent_turn([{"tool": "add_note", "args": {"text": "acheter du pain"}}]),
                agent_turn([], final="Fait."),
            ]
        )

        result = jarvis.run_agentic("note que je dois acheter du pain")

        assert result == "Fait."
        notes = jarvis.memory.recent_notes()
        assert notes.count("acheter du pain") == 1

    def test_different_args_both_executed(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI(
            [
                agent_turn([{"tool": "add_note", "args": {"text": "note A"}}]),
                agent_turn([{"tool": "add_note", "args": {"text": "note B"}}]),
                agent_turn([], final="Fait."),
            ]
        )

        jarvis.run_agentic("deux notes")

        notes = jarvis.memory.recent_notes()
        assert "note A" in notes
        assert "note B" in notes

    def test_stops_immediately_on_first_final(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI([agent_turn([], final="Bonjour")])

        result = jarvis.run_agentic("salut")

        assert result == "Bonjour"
        assert len(jarvis.ai.calls) == 1
