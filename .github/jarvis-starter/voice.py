from __future__ import annotations

import collections
import io
import os
import threading

MODEL_SIZE = "base"  # ajustable via JARVIS_WHISPER_MODEL si besoin de plus de precision
_model = None  # charge une seule fois, reutilise entre les appels


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # type: ignore

        model_size = os.environ.get("JARVIS_WHISPER_MODEL", MODEL_SIZE)
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model


def transcribe(wav_bytes: bytes) -> str:
    """Transcrit un WAV (mono, tel que produit par speech_recognition) en texte francais."""
    try:
        model = _get_model()
    except Exception as exc:
        return f"voice: whisper indisponible - {exc}"

    segments, _info = model.transcribe(io.BytesIO(wav_bytes), language="fr")
    return " ".join(segment.text.strip() for segment in segments).strip()


class _SpeechRecognitionMicrophone:
    """Enveloppe le micro reel (speech_recognition) - ouvert une seule fois, relu en boucle."""

    def __init__(self) -> None:
        import speech_recognition as sr  # type: ignore

        self._sr = sr
        self._recognizer = sr.Recognizer()
        self._microphone = sr.Microphone()
        self._source = self._microphone.__enter__()
        self._recognizer.adjust_for_ambient_noise(self._source, duration=0.4)

    def listen_chunk(self, chunk_seconds: float) -> bytes | None:
        try:
            audio = self._recognizer.listen(self._source, timeout=chunk_seconds, phrase_time_limit=chunk_seconds)
        except self._sr.WaitTimeoutError:
            return None
        return audio.get_wav_data()

    def release(self) -> None:
        self._microphone.__exit__(None, None, None)


def _open_default_microphone() -> _SpeechRecognitionMicrophone:
    return _SpeechRecognitionMicrophone()


class AudioBuffer:
    """Buffer tournant de segments audio, enregistres en arriere-plan.

    Demarrage/arret toujours explicites (`start()`/`stop()`) - jamais lance
    automatiquement. Le micro est ouvert une seule fois pendant que le
    buffer tourne et libere des `stop()`. Aucune transcription lancee ici :
    seul l'audio brut est bufferise, `transcribe()` reste a la demande.
    """

    def __init__(self, capacity: int = 10, chunk_seconds: float = 3.0, microphone_factory=None) -> None:
        self.capacity = capacity
        self.chunk_seconds = chunk_seconds
        self._microphone_factory = microphone_factory or _open_default_microphone
        self._chunks: collections.deque[bytes] = collections.deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        microphone = self._microphone_factory()
        try:
            while not self._stop_event.is_set():
                chunk = microphone.listen_chunk(self.chunk_seconds)
                if chunk is not None:
                    with self._lock:
                        self._chunks.append(chunk)
        finally:
            microphone.release()

    def latest_chunk(self) -> bytes | None:
        with self._lock:
            return self._chunks[-1] if self._chunks else None

    def chunk_count(self) -> int:
        with self._lock:
            return len(self._chunks)
