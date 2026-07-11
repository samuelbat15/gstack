from __future__ import annotations


class Notifier:
    def __init__(self) -> None:
        self.toaster = None
        self._toast_cls = None
        try:
            from windows_toasts import Toast, WindowsToaster  # type: ignore

            self.toaster = WindowsToaster("Jarvis")
            self._toast_cls = Toast
        except Exception:
            self.toaster = None

    def notify(self, title: str, message: str) -> None:
        if self.toaster is None or self._toast_cls is None:
            return
        try:
            toast = self._toast_cls()
            toast.text_fields = [title, message]
            self.toaster.show_toast(toast)
        except Exception:
            pass
