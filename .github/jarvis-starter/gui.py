from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

from jarvis import Jarvis


BG = "#0a0e14"
ENTRY_BG = "#141a24"
USER_FG = "#c9c2ff"
JARVIS_FG = "#8fd3ff"
ENTRY_BORDER_IDLE = "#141a24"
ENTRY_BORDER_FOCUS = "#8fd3ff"
BUTTON_BG = "#1c2433"
BUTTON_PRESS_BG = "#12161f"

THINKING_FRAMES = ["Jarvis reflechit.", "Jarvis reflechit..", "Jarvis reflechit..."]
THINKING_INTERVAL_MS = 350


class JarvisGUI:
    def __init__(self, jarvis: Jarvis, response_queue: "queue.Queue[str]") -> None:
        self.jarvis = jarvis
        self.response_queue = response_queue
        self._thinking_job: str | None = None
        self._thinking_frame = 0
        self.root = tk.Tk()
        self.root.title("Jarvis")
        self.root.geometry("520x600")
        self.root.configure(bg=BG)
        self._build_widgets()
        self._poll_queue()

    def _build_widgets(self) -> None:
        self.history = scrolledtext.ScrolledText(
            self.root,
            state="disabled",
            bg=BG,
            fg=JARVIS_FG,
            insertbackground=JARVIS_FG,
            font=("Consolas", 10),
            wrap="word",
        )
        self.history.tag_configure("user", foreground=USER_FG)
        self.history.tag_configure("jarvis", foreground=JARVIS_FG)
        self.history.pack(fill="both", expand=True, padx=8, pady=8)

        entry_frame = tk.Frame(self.root, bg=BG)
        entry_frame.pack(fill="x", padx=8, pady=(0, 8))

        # highlightthickness/highlightbackground double as a focus ring since
        # Tkinter has no CSS-style focus outline or transition.
        self.entry = tk.Entry(
            entry_frame,
            bg=ENTRY_BG,
            fg=JARVIS_FG,
            insertbackground=JARVIS_FG,
            highlightthickness=2,
            highlightbackground=ENTRY_BORDER_IDLE,
            highlightcolor=ENTRY_BORDER_FOCUS,
        )
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_send)

        # Keyboard-triggered send (Enter) stays instant and unanimated on
        # purpose: it's the highest-frequency action in this UI, and per
        # Emil Kowalski's animation framework, keyboard-initiated actions
        # should never animate -- it would only make sending feel slower.
        self.send_button = tk.Button(
            entry_frame,
            text="Envoyer",
            command=self._on_send,
            bg=BUTTON_BG,
            fg=JARVIS_FG,
            activebackground=BUTTON_PRESS_BG,
            activeforeground=JARVIS_FG,
            relief="flat",
            bd=0,
            padx=10,
        )
        self.send_button.pack(side="left", padx=(4, 0))
        self.send_button.bind("<ButtonPress-1>", self._on_button_press)
        self.send_button.bind("<ButtonRelease-1>", self._on_button_release)

    def _on_button_press(self, event: object = None) -> None:
        self.send_button.configure(bg=BUTTON_PRESS_BG)

    def _on_button_release(self, event: object = None) -> None:
        self.send_button.configure(bg=BUTTON_BG)

    def _append_line(self, text: str, tag: str | None = None) -> None:
        self.history.configure(state="normal")
        self.history.insert("end", text + "\n", tag)
        self.history.configure(state="disabled")
        self.history.see("end")

    def _on_send(self, event: object = None) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append_line(f"Vous: {text}", "user")
        self._append_line(THINKING_FRAMES[0], "jarvis")
        self._start_thinking_animation()
        threading.Thread(target=self._handle_safely, args=(text,), daemon=True).start()

    def _handle_safely(self, text: str) -> None:
        try:
            self.jarvis.handle(text)
        except Exception as exc:  # noqa: BLE001 - surface any error to the UI instead of a silent thread crash
            self.response_queue.put(f"Erreur interne: {exc}")

    def _start_thinking_animation(self) -> None:
        self._thinking_frame = 0
        self._tick_thinking()

    def _tick_thinking(self) -> None:
        # A cycling "..." reads as faster than a static line, even though the
        # actual wait time is identical -- perceived performance, not real
        # performance (same principle as a fast-spinning loading spinner).
        self._thinking_frame = (self._thinking_frame + 1) % len(THINKING_FRAMES)
        self.history.configure(state="normal")
        self.history.delete("end-2l", "end-1l")
        self.history.insert("end", THINKING_FRAMES[self._thinking_frame] + "\n", "jarvis")
        self.history.configure(state="disabled")
        self.history.see("end")
        self._thinking_job = self.root.after(THINKING_INTERVAL_MS, self._tick_thinking)

    def _stop_thinking_animation(self) -> None:
        if self._thinking_job is not None:
            self.root.after_cancel(self._thinking_job)
            self._thinking_job = None

    def _poll_queue(self) -> None:
        try:
            while True:
                text = self.response_queue.get_nowait()
                self._replace_thinking(text)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _replace_thinking(self, text: str) -> None:
        self._stop_thinking_animation()
        self.history.configure(state="normal")
        self.history.delete("end-2l", "end-1l")
        self.history.insert("end", f"Jarvis: {text}\n", "jarvis")
        self.history.configure(state="disabled")
        self.history.see("end")

    def run(self) -> None:
        self.root.mainloop()


def deny_in_gui(action: str) -> bool:
    return False
