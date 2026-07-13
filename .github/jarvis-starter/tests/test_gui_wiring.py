from __future__ import annotations

from pathlib import Path

from jarvis import Config, Jarvis, Speaker


def make_jarvis(tmp_path, **kwargs) -> Jarvis:
    config = Config(assistant_name="Jarvis", confirm_actions=True, sites={}, apps={})
    return Jarvis(config=config, voice=False, data_dir=tmp_path, vault_path=tmp_path / "vault", **kwargs)


class TestSpeakerSink:
    def test_sink_receives_text_instead_of_print(self):
        received = []
        speaker = Speaker(enabled=False, name="Jarvis", sink=received.append)
        speaker.say("bonjour")
        assert received == ["bonjour"]

    def test_no_sink_does_not_raise(self, capsys):
        speaker = Speaker(enabled=False, name="Jarvis")
        speaker.say("bonjour")
        captured = capsys.readouterr()
        assert "bonjour" in captured.out


class TestJarvisOutputSink:
    def test_output_sink_is_wired_to_speaker(self, tmp_path):
        received = []
        jarvis = make_jarvis(tmp_path, output_sink=received.append)
        jarvis.speaker.say("test")
        assert received == ["test"]

    def test_no_output_sink_keeps_print_behavior(self, tmp_path, capsys):
        jarvis = make_jarvis(tmp_path)
        jarvis.speaker.say("test")
        captured = capsys.readouterr()
        assert "test" in captured.out


class TestJarvisConfirmFn:
    def test_confirm_fn_overrides_input(self, tmp_path):
        jarvis = make_jarvis(tmp_path, confirm_fn=lambda action: False)
        assert jarvis.confirm("ouvrir youtube") is False

    def test_confirm_fn_true_bypasses_input(self, tmp_path):
        jarvis = make_jarvis(tmp_path, confirm_fn=lambda action: True)
        assert jarvis.confirm("ouvrir youtube") is True

    def test_no_confirm_fn_uses_input(self, tmp_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda prompt: "oui")
        jarvis = make_jarvis(tmp_path)
        assert jarvis.confirm("ouvrir youtube") is True
