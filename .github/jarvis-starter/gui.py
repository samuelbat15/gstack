from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

from jarvis import Jarvis


class JarvisGUI:
    def __init__(self, jarvis: Jarvis, response_queue: "queue.Queue[str]") -> None:
        self.jarvis = jarvis
        self.response_queue = response_queue
        self.root = tk.Tk()
        self.root.title("Jarvis")
        self.root.geometry("520x600")
        self.root.configure(bg="#0a0e14")
        self._build_widgets()
        self._poll_queue()

    def _build_widgets(self) -> None:
        self.history = scrolledtext.ScrolledText(
            self.root,
            state="disabled",
            bg="#0a0e14",
            fg="#8fd3ff",
            insertbackground="#8fd3ff",
            font=("Consolas", 10),
            wrap="word",
        )
        self.history.pack(fill="both", expand=True, padx=8, pady=8)

        entry_frame = tk.Frame(self.root, bg="#0a0e14")
        entry_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.entry = tk.Entry(entry_frame, bg="#141a24", fg="#8fd3ff", insertbackground="#8fd3ff")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_send)

        tk.Button(entry_frame, text="Envoyer", command=self._on_send).pack(side="left", padx=(4, 0))

    def _append_line(self, text: str) -> None:
        self.history.configure(state="normal")
        self.history.insert("end", text + "\n")
        self.history.configure(state="disabled")
        self.history.see("end")

    def _on_send(self, event: object = None) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append_line(f"Vous: {text}")
        self._append_line("Jarvis reflechit...")
        threading.Thread(target=self._handle_safely, args=(text,), daemon=True).start()

    def _handle_safely(self, text: str) -> None:
        try:
            self.jarvis.handle(text)
        except Exception as exc:  # noqa: BLE001 - surface any error to the UI instead of a silent thread crash
            self.response_queue.put(f"Erreur interne: {exc}")

    def _poll_queue(self) -> None:
        try:
            while True:
                text = self.response_queue.get_nowait()
                self._replace_thinking(text)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _replace_thinking(self, text: str) -> None:
        self.history.configure(state="normal")
        self.history.delete("end-2l", "end-1l")
        self.history.insert("end", f"Jarvis: {text}\n")
        self.history.configure(state="disabled")
        self.history.see("end")

    def run(self) -> None:
        self.root.mainloop()


def deny_in_gui(action: str) -> bool:
    return False
