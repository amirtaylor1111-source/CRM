from datetime import datetime, timedelta, timezone

from notetaker import store, uistate


def iso(minutes):
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class TestFormatting:
    def test_elapsed_under_an_hour(self):
        assert uistate.elapsed_text(0) == "00:00"
        assert uistate.elapsed_text(65) == "01:05"

    def test_elapsed_over_an_hour(self):
        assert uistate.elapsed_text(3725) == "1:02:05"

    def test_elapsed_never_negative(self):
        assert uistate.elapsed_text(-10) == "00:00"

    def test_friendly_when_handles_today(self):
        assert uistate.friendly_when(iso(60)).startswith(("Today", "Tomorrow"))

    def test_friendly_when_survives_rubbish(self):
        assert uistate.friendly_when("not a date") == "not a date"
        assert uistate.friendly_when("") == ""


class TestStartGate:
    def test_blocked_until_consent(self):
        assert not uistate.can_start(uistate.IDLE, consent_given=False, solo=False)

    def test_allowed_once_confirmed(self):
        assert uistate.can_start(uistate.IDLE, consent_given=True, solo=False)

    def test_solo_bypasses_consent(self):
        assert uistate.can_start(uistate.IDLE, consent_given=False, solo=True)

    def test_never_while_busy(self):
        for state in (uistate.RECORDING, uistate.TRANSCRIBING):
            assert not uistate.can_start(state, True, True)


class TestSuggestion:
    def test_prefills_from_a_meeting_starting_soon(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        d = store.create_meeting("seed", root=crm)
        store.link_contact(d, "Monty Smythe", root=crm, email="m@out.com")
        store.save_calendar([{"subject": "Catchup", "start": iso(5), "end": iso(35),
                              "attendees": ["m@out.com"]}], root=crm)
        s = uistate.suggest(store, window_minutes=30)
        assert s.title == "Catchup"
        assert s.participants == ["Monty Smythe"]
        assert s.source == "calendar"

    def test_does_not_guess_a_title_for_a_distant_meeting(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        store.save_calendar([{"subject": "Next week", "start": iso(5000),
                              "end": iso(5030)}], root=crm)
        s = uistate.suggest(store, window_minutes=30)
        assert s.title == ""
        assert s.source == "calendar-later"

    def test_empty_calendar_is_not_an_error(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        s = uistate.suggest(store)
        assert s.title == ""
        assert s.headline == "No meeting scheduled"


class TestLabels:
    def test_button_changes_with_state(self):
        assert uistate.button_label(uistate.IDLE) == "Start recording"
        assert uistate.button_label(uistate.RECORDING) == "Stop"

    def test_status_points_at_the_next_step_when_done(self):
        assert "/notes" in uistate.status_line(uistate.DONE)
