from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

RELATIVE_RE = re.compile(r"^dans\s+(\d+)\s*(minutes?|heures?)$", re.IGNORECASE)
ABSOLUTE_RE = re.compile(r"^a\s+(\d{1,2})[h:](\d{2})?$", re.IGNORECASE)


def parse_reminder_time(when_text: str, now: datetime) -> datetime | None:
    when_text = when_text.strip()

    match = RELATIVE_RE.match(when_text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        delta = timedelta(hours=amount) if unit.startswith("heure") else timedelta(minutes=amount)
        return now + delta

    match = ABSOLUTE_RE.match(when_text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        trigger_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if trigger_at <= now:
            trigger_at += timedelta(days=1)
        return trigger_at

    return None


def split_reminder_command(remainder: str) -> tuple[str, str] | None:
    match = re.match(r"^(.*?)\s+de\s+(.+)$", remainder, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


class ReminderStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "reminders.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, reminders: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(reminders, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, text: str, trigger_at: datetime) -> dict[str, Any]:
        reminders = self._load()
        reminder = {
            "id": str(uuid.uuid4()),
            "text": text,
            "trigger_at": trigger_at.isoformat(),
            "created_at": datetime.now().isoformat(),
            "fired": False,
        }
        reminders.append(reminder)
        self._save(reminders)
        return reminder

    def pending(self) -> list[dict[str, Any]]:
        return [r for r in self._load() if not r.get("fired")]

    def due(self, now: datetime) -> list[dict[str, Any]]:
        return [r for r in self.pending() if datetime.fromisoformat(r["trigger_at"]) <= now]

    def mark_fired(self, reminder_id: str) -> None:
        reminders = self._load()
        for reminder in reminders:
            if reminder["id"] == reminder_id:
                reminder["fired"] = True
        self._save(reminders)
