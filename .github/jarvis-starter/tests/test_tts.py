from __future__ import annotations

import tts


class FakeConvert:
    def __init__(self, result="fake-audio-bytes", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class FakeTextToSpeech:
    def __init__(self, convert: FakeConvert) -> None:
        self.convert = convert


class FakeClient:
    def __init__(self, convert: FakeConvert) -> None:
        self.text_to_speech = FakeTextToSpeech(convert)


class TestSpeak:
    def test_missing_api_key_returns_false_without_calling_client(self, monkeypatch):
        called = []
        monkeypatch.setattr("tts._get_client", lambda api_key: called.append(1))
        assert tts.speak("bonjour", api_key="", voice_id="voice123") is False
        assert called == []

    def test_missing_voice_id_returns_false_without_calling_client(self, monkeypatch):
        called = []
        monkeypatch.setattr("tts._get_client", lambda api_key: called.append(1))
        assert tts.speak("bonjour", api_key="key123", voice_id="") is False
        assert called == []

    def test_empty_text_returns_false(self, monkeypatch):
        called = []
        monkeypatch.setattr("tts._get_client", lambda api_key: called.append(1))
        assert tts.speak("   ", api_key="key123", voice_id="voice123") is False
        assert called == []

    def test_successful_call_plays_audio_and_returns_true(self, monkeypatch):
        convert = FakeConvert(result="the-audio")
        monkeypatch.setattr("tts._get_client", lambda api_key: FakeClient(convert))
        played = []
        monkeypatch.setattr("tts._play_audio", played.append)

        result = tts.speak("bonjour", api_key="key123", voice_id="voice123", model_id="eleven_multilingual_v2")

        assert result is True
        assert played == ["the-audio"]
        assert convert.calls == [
            {
                "text": "bonjour",
                "voice_id": "voice123",
                "model_id": "eleven_multilingual_v2",
                "output_format": tts.OUTPUT_FORMAT,
            }
        ]

    def test_client_unavailable_returns_false(self, monkeypatch):
        def raise_error(api_key):
            raise RuntimeError("elevenlabs non installe")

        monkeypatch.setattr("tts._get_client", raise_error)
        assert tts.speak("bonjour", api_key="key123", voice_id="voice123") is False

    def test_convert_failure_returns_false(self, monkeypatch):
        convert = FakeConvert(error=RuntimeError("401 unauthorized"))
        monkeypatch.setattr("tts._get_client", lambda api_key: FakeClient(convert))
        assert tts.speak("bonjour", api_key="wrong-key", voice_id="voice123") is False

    def test_play_failure_returns_false(self, monkeypatch):
        convert = FakeConvert(result="the-audio")
        monkeypatch.setattr("tts._get_client", lambda api_key: FakeClient(convert))

        def raise_play(audio):
            raise RuntimeError("mpv/ffmpeg introuvable")

        monkeypatch.setattr("tts._play_audio", raise_play)
        assert tts.speak("bonjour", api_key="key123", voice_id="voice123") is False
