from __future__ import annotations

from notifications import Notifier


def test_notifier_never_raises_on_construction():
    Notifier()


def test_notify_never_raises_without_windows_toasts():
    notifier = Notifier()
    notifier.notify("Jarvis", "test de notification")
