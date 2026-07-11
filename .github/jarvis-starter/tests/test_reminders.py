from __future__ import annotations

from datetime import datetime

from reminders import ReminderStore, parse_reminder_time, split_reminder_command


class TestParseReminderTime:
    def test_relative_minutes(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("dans 20 minutes", now)
        assert result == datetime(2026, 7, 11, 15, 20, 0)

    def test_relative_hours(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("dans 2 heures", now)
        assert result == datetime(2026, 7, 11, 17, 0, 0)

    def test_absolute_with_minutes(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 18h30", now)
        assert result == datetime(2026, 7, 11, 18, 30, 0)

    def test_absolute_colon_syntax(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 18:30", now)
        assert result == datetime(2026, 7, 11, 18, 30, 0)

    def test_absolute_hour_only_defaults_to_zero_minutes(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 9h", now)
        assert result == datetime(2026, 7, 12, 9, 0, 0)

    def test_absolute_already_past_schedules_tomorrow(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 9h00", now)
        assert result == datetime(2026, 7, 12, 9, 0, 0)

    def test_invalid_format_returns_none(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        assert parse_reminder_time("demain matin", now) is None


class TestSplitReminderCommand:
    def test_valid_split(self):
        result = split_reminder_command("dans 20 minutes de appeler Sam")
        assert result == ("dans 20 minutes", "appeler Sam")

    def test_no_separator_returns_none(self):
        assert split_reminder_command("dans 20 minutes appeler Sam") is None

    def test_splits_on_first_de_only(self):
        result = split_reminder_command("a 18h de parler de la campagne SEO")
        assert result == ("a 18h", "parler de la campagne SEO")


class TestReminderStore:
    def test_add_then_pending(self, tmp_path):
        store = ReminderStore(tmp_path)
        store.add("appeler Sam", datetime(2026, 7, 11, 18, 0, 0))
        pending = store.pending()
        assert len(pending) == 1
        assert pending[0]["text"] == "appeler Sam"
        assert pending[0]["fired"] is False

    def test_due_filters_by_time(self, tmp_path):
        store = ReminderStore(tmp_path)
        store.add("passe", datetime(2026, 7, 11, 10, 0, 0))
        store.add("futur", datetime(2026, 7, 11, 20, 0, 0))
        due = store.due(datetime(2026, 7, 11, 15, 0, 0))
        assert [r["text"] for r in due] == ["passe"]

    def test_mark_fired_removes_from_pending(self, tmp_path):
        store = ReminderStore(tmp_path)
        reminder = store.add("appeler Sam", datetime(2026, 7, 11, 18, 0, 0))
        store.mark_fired(reminder["id"])
        assert store.pending() == []
