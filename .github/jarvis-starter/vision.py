from __future__ import annotations

import base64
import collections
import json
import os
import threading
import urllib.error
import urllib.request

DEFAULT_MODEL = "moondream"  # deja valide localement sur ce poste (mma-analyzer)
DEFAULT_BASE_URL = "http://localhost:11434"
# Prompt court a dessein : verifie le 2026-07-16, une instruction composee
# ("decris + en francais + de maniere concise") fait deraper moondream
# (reponse degeneree du type "!!!"). moondream (1.6B) ne suit pas non plus
# la consigne de langue de maniere fiable - reponses en anglais malgre un
# prompt francais, limite connue du modele, pas un bug du code.
DEFAULT_PROMPT = "Decris ce que tu vois."


def capture_photo() -> bytes:
    """Capture une seule photo depuis la webcam par defaut, encodee en JPEG.

    Leve une exception si la camera est absente/deja utilisee - la camera
    est toujours liberee (finally), jamais laissee ouverte apres l'appel.
    """
    import cv2  # type: ignore

    camera = cv2.VideoCapture(0)
    try:
        if not camera.isOpened():
            raise RuntimeError("webcam introuvable ou deja utilisee par une autre application")
        ok, frame = camera.read()
        if not ok:
            raise RuntimeError("echec de capture (aucune image lue)")
        success, buffer = cv2.imencode(".jpg", frame)
        if not success:
            raise RuntimeError("echec d'encodage JPEG")
        return buffer.tobytes()
    finally:
        camera.release()


def describe_image(image_bytes: bytes, question: str = "") -> str:
    """Envoie une image a un modele vision local (Ollama) et retourne sa description.

    Leve une exception si Ollama est injoignable ou le modele indisponible.
    """
    model = os.environ.get("JARVIS_VISION_MODEL", "").strip() or DEFAULT_MODEL
    base_url = (os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")
    prompt = question.strip() or DEFAULT_PROMPT

    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # 120s : le premier appel (chargement du modele) a mesure jusqu'a 78s
    # sur CPU seul (verifie le 2026-07-16, meme machine que qwen2.5:7b).
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))

    answer = payload.get("response")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()
    return "vision: reponse vide du modele"


class _Cv2Camera:
    """Enveloppe la webcam reelle (cv2) - ouverte une seule fois, relue en boucle."""

    def __init__(self) -> None:
        import cv2  # type: ignore

        self._cv2 = cv2
        self._camera = cv2.VideoCapture(0)
        if not self._camera.isOpened():
            raise RuntimeError("webcam introuvable ou deja utilisee par une autre application")

    def read_jpeg(self) -> bytes | None:
        ok, frame = self._camera.read()
        if not ok:
            return None
        success, buffer = self._cv2.imencode(".jpg", frame)
        if not success:
            return None
        return buffer.tobytes()

    def release(self) -> None:
        self._camera.release()


def _open_default_camera() -> _Cv2Camera:
    return _Cv2Camera()


class VisionBuffer:
    """Buffer tournant de frames webcam, capturees en arriere-plan.

    Demarrage/arret toujours explicites (`start()`/`stop()`) - jamais lance
    automatiquement. La camera est ouverte une seule fois pendant que le
    buffer tourne (pas de reouverture a chaque frame, contrairement a
    capture_photo()) et liberee des `stop()`. Aucune inference lancee ici :
    trop couteux en continu sur ce poste (CPU seul, ~6-78s par description).
    """

    def __init__(self, capacity: int = 10, interval: float = 2.0, camera_factory=None) -> None:
        self.capacity = capacity
        self.interval = interval
        self._camera_factory = camera_factory or _open_default_camera
        self._frames: collections.deque[bytes] = collections.deque(maxlen=capacity)
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
        camera = self._camera_factory()
        try:
            while not self._stop_event.is_set():
                frame_bytes = camera.read_jpeg()
                if frame_bytes is not None:
                    with self._lock:
                        self._frames.append(frame_bytes)
                self._stop_event.wait(self.interval)
        finally:
            camera.release()

    def latest_frame(self) -> bytes | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def frame_count(self) -> int:
        with self._lock:
            return len(self._frames)


def describe_scene(question: str = "") -> str:
    """Capture une photo et la decrit via le modele vision local.

    Ne leve jamais d'exception : webcam absente, Ollama injoignable, ou
    modele vision non installe -> chaine "vision: ..." retournee, jamais
    de crash (meme contrat que voice.transcribe()).
    """
    try:
        image_bytes = capture_photo()
        return describe_image(image_bytes, question)
    except Exception as exc:
        return f"vision: {exc}"
