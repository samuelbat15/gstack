from __future__ import annotations

DEFAULT_MODEL = "eleven_multilingual_v2"  # supporte le francais, contrairement au v3 alpha
OUTPUT_FORMAT = "mp3_44100_128"

_client = None  # charge une seule fois, reutilise entre les appels


def _get_client(api_key: str):
    global _client
    if _client is None:
        from elevenlabs.client import ElevenLabs  # type: ignore

        _client = ElevenLabs(api_key=api_key)
    return _client


def _play_audio(audio) -> None:
    from elevenlabs.play import play  # type: ignore

    play(audio)


def speak(text: str, api_key: str, voice_id: str, model_id: str = DEFAULT_MODEL) -> bool:
    """Synthetise et joue `text` via ElevenLabs.

    Retourne False (jamais d'exception) des qu'une etape echoue - cle/voix
    manquante, paquet non installe, erreur reseau - pour que l'appelant
    puisse basculer sur un moteur de secours local (pyttsx3).
    """
    if not api_key or not voice_id or not text.strip():
        return False

    try:
        client = _get_client(api_key)
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=OUTPUT_FORMAT,
        )
        _play_audio(audio)
        return True
    except Exception:
        return False
