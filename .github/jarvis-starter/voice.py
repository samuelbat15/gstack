from __future__ import annotations

import io
import os

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
