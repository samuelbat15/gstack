from __future__ import annotations

import time

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


class FakeMicrophone:
    def __init__(self, chunks=None):
        self.chunks = list(chunks) if chunks is not None else [b"chunk-1", b"chunk-2", b"chunk-3"]
        self._index = 0
        self.released = False

    def listen_chunk(self, chunk_seconds):
        chunk = self.chunks[self._index % len(self.chunks)]
        self._index += 1
        return chunk

    def release(self):
        self.released = True


def _wait_until(predicate, timeout=2.0, step=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


class TestAudioBuffer:
    def test_start_populates_chunks_then_stop_releases_microphone(self):
        mic = FakeMicrophone()
        buf = voice.AudioBuffer(capacity=3, chunk_seconds=0.01, microphone_factory=lambda: mic)

        buf.start()
        assert _wait_until(lambda: buf.chunk_count() >= 3)
        assert buf.is_running() is True
        assert buf.latest_chunk() in mic.chunks

        buf.stop()
        assert buf.is_running() is False
        assert mic.released is True

    def test_capacity_caps_stored_chunks(self):
        mic = FakeMicrophone(chunks=[b"c1", b"c2", b"c3", b"c4", b"c5"])
        buf = voice.AudioBuffer(capacity=2, chunk_seconds=0.01, microphone_factory=lambda: mic)

        buf.start()
        assert _wait_until(lambda: mic._index >= 5)
        assert buf.chunk_count() == 2
        buf.stop()

    def test_no_chunks_yet_latest_chunk_is_none(self):
        mic = FakeMicrophone()
        buf = voice.AudioBuffer(capacity=3, chunk_seconds=10.0, microphone_factory=lambda: mic)
        assert buf.latest_chunk() is None
        assert buf.chunk_count() == 0

    def test_start_is_idempotent_while_running(self):
        mic = FakeMicrophone()
        buf = voice.AudioBuffer(capacity=3, chunk_seconds=0.01, microphone_factory=lambda: mic)
        buf.start()
        assert _wait_until(lambda: buf.chunk_count() >= 1)
        first_thread = buf._thread
        buf.start()
        assert buf._thread is first_thread
        buf.stop()

    def test_none_chunk_from_microphone_is_skipped(self):
        class SilentThenSpeechMicrophone:
            def __init__(self):
                self.calls = 0
                self.released = False

            def listen_chunk(self, chunk_seconds):
                self.calls += 1
                return None if self.calls <= 2 else b"speech-chunk"

            def release(self):
                self.released = True

        mic = SilentThenSpeechMicrophone()
        buf = voice.AudioBuffer(capacity=3, chunk_seconds=0.01, microphone_factory=lambda: mic)
        buf.start()
        assert _wait_until(lambda: buf.chunk_count() >= 1)
        assert buf.latest_chunk() == b"speech-chunk"
        buf.stop()
