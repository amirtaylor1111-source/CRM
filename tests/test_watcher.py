from datetime import datetime, timedelta, timezone

from notetaker import store, watcher


def iso(minutes):
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class TestDueNow:
    def test_offers_a_meeting_starting_now(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        store.save_calendar([{"subject": "Catchup", "start": iso(1), "end": iso(31)}],
                            root=crm)
        assert watcher.due_now(set())["subject"] == "Catchup"

    def test_stays_quiet_for_a_meeting_hours_away(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        store.save_calendar([{"subject": "Later", "start": iso(300), "end": iso(330)}],
                            root=crm)
        assert watcher.due_now(set()) is None

    def test_offers_each_meeting_only_once(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        store.save_calendar([{"subject": "Catchup", "start": iso(1), "end": iso(31)}],
                            root=crm)
        seen = set()
        first = watcher.due_now(seen)
        seen.add(watcher.event_key(first))
        assert watcher.due_now(seen) is None

    def test_does_not_nag_when_already_recorded(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        event = {"subject": "Catchup", "start": iso(1), "end": iso(31)}
        store.save_calendar([event], root=crm)
        store.create_meeting("Catchup", root=crm)
        assert watcher.already_recorded(event) is True
        assert watcher.due_now(set()) is None

    def test_empty_calendar_is_quiet(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        assert watcher.due_now(set()) is None

    def test_key_distinguishes_repeats_of_the_same_title(self):
        a = {"subject": "Standup", "start": "2026-09-07T09:00:00Z"}
        b = {"subject": "Standup", "start": "2026-09-08T09:00:00Z"}
        assert watcher.event_key(a) != watcher.event_key(b)
