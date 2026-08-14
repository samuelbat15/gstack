from __future__ import annotations

import time

from jarvis import BufferWatcher


def _wait_until(predicate, timeout=2.0, step=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


class TestBufferWatcher:
    def test_analyzes_latest_item_periodically(self):
        results = []
        watcher = BufferWatcher(
            get_latest=lambda: "frame-bytes",
            describe=lambda item: f"description de {item}",
            on_result=results.append,
            interval=0.01,
        )
        watcher.start()
        assert _wait_until(lambda: len(results) >= 2)
        watcher.stop()
        assert all(r == "description de frame-bytes" for r in results)

    def test_none_latest_item_is_skipped(self):
        results = []
        watcher = BufferWatcher(
            get_latest=lambda: None,
            describe=lambda item: "ne devrait jamais etre appele",
            on_result=results.append,
            interval=0.01,
        )
        watcher.start()
        time.sleep(0.1)
        watcher.stop()
        assert results == []

    def test_empty_string_result_is_not_reported(self):
        results = []
        watcher = BufferWatcher(
            get_latest=lambda: "item",
            describe=lambda item: "",
            on_result=results.append,
            interval=0.01,
        )
        watcher.start()
        time.sleep(0.1)
        watcher.stop()
        assert results == []

    def test_describe_exception_is_reported_not_raised(self):
        results = []

        def raise_error(item):
            raise RuntimeError("modele indisponible")

        watcher = BufferWatcher(
            get_latest=lambda: "item",
            describe=raise_error,
            on_result=results.append,
            interval=0.01,
        )
        watcher.start()
        assert _wait_until(lambda: len(results) >= 1)
        watcher.stop()
        assert "modele indisponible" in results[0]

    def test_stop_stops_the_thread(self):
        watcher = BufferWatcher(
            get_latest=lambda: "item",
            describe=lambda item: "ok",
            on_result=lambda text: None,
            interval=0.01,
        )
        watcher.start()
        assert _wait_until(lambda: watcher.is_running())
        watcher.stop()
        assert _wait_until(lambda: not watcher.is_running())
