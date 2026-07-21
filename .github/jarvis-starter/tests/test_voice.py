from __future__ import annotations

import voice


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class TestTranscribe:
    def test_concatenates_segments(self, monkeypatch):
        class FakeModel:
            def transcribe(self, audio, language):
                return [FakeSegment(" Bonjour "), FakeSegment(" Jarvis ")], None

        monkeypatch.setattr("voice._get_model", lambda: FakeModel())
        result = voice.transcribe(b"fake-wav-bytes")
        assert result == "Bonjour Jarvis"

    def test_empty_segments_returns_empty_string(self, monkeypatch):
        class FakeModel:
            def transcribe(self, audio, language):
                return [], None

        monkeypatch.setattr("voice._get_model", lambda: FakeModel())
        result = voice.transcribe(b"fake-wav-bytes")
        assert result == ""

    def test_model_unavailable_returns_error_string(self, monkeypatch):
        def raise_error():
            raise RuntimeError("faster-whisper non installe")

        monkeypatch.setattr("voice._get_model", raise_error)
        result = voice.transcribe(b"fake-wav-bytes")
        assert result.startswith("voice: whisper indisponible")
