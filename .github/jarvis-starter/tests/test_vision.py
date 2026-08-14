from __future__ import annotations

import time

import vision


class FakeCamera:
    def __init__(self, frames=None):
        self.frames = list(frames) if frames is not None else [b"frame-1", b"frame-2", b"frame-3"]
        self._index = 0
        self.released = False

    def read_jpeg(self):
        frame = self.frames[self._index % len(self.frames)]
        self._index += 1
        return frame

    def release(self):
        self.released = True


def _wait_until(predicate, timeout=2.0, step=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


class TestVisionBuffer:
    def test_start_populates_frames_then_stop_releases_camera(self):
        camera = FakeCamera()
        buf = vision.VisionBuffer(capacity=3, interval=0.01, camera_factory=lambda: camera)

        buf.start()
        assert _wait_until(lambda: buf.frame_count() >= 3)
        assert buf.is_running() is True
        assert buf.latest_frame() in camera.frames

        buf.stop()
        assert buf.is_running() is False
        assert camera.released is True

    def test_capacity_caps_stored_frames(self):
        camera = FakeCamera(frames=[b"f1", b"f2", b"f3", b"f4", b"f5"])
        buf = vision.VisionBuffer(capacity=2, interval=0.01, camera_factory=lambda: camera)

        buf.start()
        assert _wait_until(lambda: camera._index >= 5)
        assert buf.frame_count() == 2
        buf.stop()

    def test_no_frames_yet_latest_frame_is_none(self):
        camera = FakeCamera()
        buf = vision.VisionBuffer(capacity=3, interval=10.0, camera_factory=lambda: camera)
        assert buf.latest_frame() is None
        assert buf.frame_count() == 0

    def test_start_is_idempotent_while_running(self):
        camera = FakeCamera()
        buf = vision.VisionBuffer(capacity=3, interval=0.01, camera_factory=lambda: camera)
        buf.start()
        assert _wait_until(lambda: buf.frame_count() >= 1)
        first_thread = buf._thread
        buf.start()
        assert buf._thread is first_thread
        buf.stop()


class TestDescribeScene:
    def test_combines_capture_and_describe(self, monkeypatch):
        monkeypatch.setattr("vision.capture_photo", lambda: b"fake-jpeg-bytes")
        calls = []
        monkeypatch.setattr(
            "vision.describe_image",
            lambda image_bytes, question: calls.append((image_bytes, question)) or "Il y a un chat.",
        )

        result = vision.describe_scene("Qu'est-ce que tu vois ?")

        assert result == "Il y a un chat."
        assert calls == [(b"fake-jpeg-bytes", "Qu'est-ce que tu vois ?")]

    def test_default_question_is_empty_string(self, monkeypatch):
        monkeypatch.setattr("vision.capture_photo", lambda: b"fake-jpeg-bytes")
        calls = []
        monkeypatch.setattr(
            "vision.describe_image", lambda image_bytes, question: calls.append(question) or "ok"
        )

        vision.describe_scene()

        assert calls == [""]

    def test_camera_failure_returns_error_string(self, monkeypatch):
        def raise_camera_error():
            raise RuntimeError("webcam introuvable ou deja utilisee par une autre application")

        monkeypatch.setattr("vision.capture_photo", raise_camera_error)
        result = vision.describe_scene()
        assert result.startswith("vision: ")
        assert "webcam introuvable" in result

    def test_model_failure_returns_error_string(self, monkeypatch):
        monkeypatch.setattr("vision.capture_photo", lambda: b"fake-jpeg-bytes")

        def raise_model_error(image_bytes, question):
            raise RuntimeError("Ollama injoignable")

        monkeypatch.setattr("vision.describe_image", raise_model_error)
        result = vision.describe_scene()
        assert result.startswith("vision: ")
        assert "Ollama injoignable" in result


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestDescribeImage:
    def test_sends_base64_image_and_returns_response_text(self, monkeypatch):
        captured_requests = []

        def fake_urlopen(request, timeout):
            captured_requests.append(request)
            return FakeResponse({"response": "Une tasse de cafe sur un bureau."})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        result = vision.describe_image(b"fake-jpeg-bytes", "Que vois-tu ?")

        assert result == "Une tasse de cafe sur un bureau."
        assert len(captured_requests) == 1

    def test_empty_model_response_returns_placeholder(self, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse({"response": ""}))
        result = vision.describe_image(b"fake-jpeg-bytes")
        assert result == "vision: reponse vide du modele"
