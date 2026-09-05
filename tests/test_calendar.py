from datetime import datetime, timedelta, timezone

from notetaker import store


def iso(dt):
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def at(minutes):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


class TestCalendar:
    def test_round_trip(self, crm):
        store.save_calendar([{"subject": "X", "start": iso(at(60)), "end": iso(at(90)),
                              "attendees": ["a@b.com"]}], root=crm)
        assert store.load_calendar(root=crm)[0]["subject"] == "X"

    def test_missing_calendar_is_empty_not_an_error(self, crm):
        assert store.load_calendar(root=crm) == []
        assert store.upcoming(root=crm) == []
        assert store.current_or_next(root=crm) is None

    def test_past_events_are_not_upcoming(self, crm):
        store.save_calendar([
            {"subject": "Over", "start": iso(at(-120)), "end": iso(at(-90))},
            {"subject": "Later", "start": iso(at(60)), "end": iso(at(90))},
        ], root=crm)
        assert [e["subject"] for e in store.upcoming(root=crm)] == ["Later"]

    def test_events_are_sorted_by_start(self, crm):
        store.save_calendar([
            {"subject": "Second", "start": iso(at(120)), "end": iso(at(150))},
            {"subject": "First", "start": iso(at(30)), "end": iso(at(60))},
        ], root=crm)
        assert [e["subject"] for e in store.upcoming(root=crm)] == ["First", "Second"]

    def test_meeting_in_progress_is_the_one_to_record(self, crm):
        store.save_calendar([{"subject": "Running", "start": iso(at(-10)),
                              "end": iso(at(20))}], root=crm)
        assert store.current_or_next(root=crm)["subject"] == "Running"

    def test_meeting_starting_soon_is_picked_up(self, crm):
        store.save_calendar([{"subject": "Soon", "start": iso(at(5)),
                              "end": iso(at(35))}], root=crm)
        assert store.current_or_next(window_minutes=15, root=crm)["subject"] == "Soon"

    def test_meeting_beyond_the_window_is_not(self, crm):
        store.save_calendar([{"subject": "Tomorrow", "start": iso(at(600)),
                              "end": iso(at(630))}], root=crm)
        assert store.current_or_next(window_minutes=15, root=crm) is None

    def test_malformed_timestamps_do_not_crash(self, crm):
        store.save_calendar([{"subject": "Bad", "start": "not a date", "end": ""}],
                            root=crm)
        assert store.upcoming(root=crm) == []
        assert store.current_or_next(root=crm) is None


class TestAttendeeNames:
    def test_resolves_known_address_to_the_crm_name(self, crm):
        d = store.create_meeting("Call", root=crm)
        store.link_contact(d, "Monty Smythe", root=crm, email="montysmythe@outlook.com")
        event = {"attendees": ["montysmythe@outlook.com"]}
        assert store.attendee_names(event, root=crm) == ["Monty Smythe"]

    def test_falls_back_to_the_local_part_for_strangers(self, crm):
        event = {"attendees": ["llewelyn.padiachy@example.com"]}
        assert store.attendee_names(event, root=crm) == ["Llewelyn Padiachy"]

    def test_excludes_the_user_themselves(self, crm):
        event = {"attendees": ["me@mine.com", "them@theirs.com"]}
        names = store.attendee_names(event, me="ME@MINE.COM", root=crm)
        assert names == ["Them"]

    def test_lookup_is_case_insensitive(self, crm):
        d = store.create_meeting("Call", root=crm)
        store.link_contact(d, "Danian Romans", root=crm, email="danian.romans@sanlam.co.za")
        event = {"attendees": ["Danian.Romans@Sanlam.co.za"]}
        assert store.attendee_names(event, root=crm) == ["Danian Romans"]


class TestImport:
    def test_import_is_idempotent_on_source_id(self, crm):
        entry = {"title": "Call", "date": "2026-09-04", "source": "fathom",
                 "source_id": "123", "participants": [{"name": "Jane Doe"}]}
        assert store.import_batch([entry], root=crm) == {"created": 1, "updated": 0}
        assert store.import_batch([entry], root=crm) == {"created": 0, "updated": 1}
        assert len(list((crm / "meetings").glob("*/"))) == 1

    def test_reimport_adds_a_transcript_without_duplicating(self, crm):
        entry = {"title": "Call", "date": "2026-09-04", "source": "fathom",
                 "source_id": "123"}
        store.import_batch([entry], root=crm)
        store.import_batch([{**entry, "transcript_md": "Speaker: hello"}], root=crm)
        dirs = list((crm / "meetings").glob("*/"))
        assert len(dirs) == 1
        assert (dirs[0] / "transcript.md").exists()

    def test_bare_email_participant_becomes_a_usable_name(self, crm):
        store.import_batch([{"title": "C", "date": "2026-09-04", "source_id": "9",
                             "participants": ["mfavero@solugrowth.com"]}], root=crm)
        assert "mfavero" in store.list_contacts(root=crm)

    def test_imported_consent_is_recorded_honestly(self, crm):
        store.import_batch([{"title": "C", "date": "2026-09-04", "source": "fathom",
                             "source_id": "7"}], root=crm)
        meeting = store.load_meeting(list((crm / "meetings").glob("*/"))[0])
        assert "fathom" in meeting.consent_note
