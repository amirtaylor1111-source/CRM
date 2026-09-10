import json
import os
import time

import pytest

from notetaker import store
from notetaker.schema import utcnow


class TestMeetings:
    def test_create_and_load(self, crm):
        d = store.create_meeting("Acme Q3", ["Jane Doe"], True, "told them", root=crm)
        meeting = store.load_meeting(d)
        assert meeting.title == "Acme Q3"
        assert meeting.consent_obtained is True
        assert meeting.participants[0].name == "Jane Doe"

    def test_consent_is_persisted_as_data(self, crm):
        d = store.create_meeting("X", [], False, "solo", root=crm)
        raw = json.loads((d / "meeting.json").read_text())
        assert raw["consent_obtained"] is False
        assert raw["consent_note"] == "solo"

    def test_same_day_collision_gets_suffix(self, crm):
        a = store.create_meeting("Standup", root=crm)
        b = store.create_meeting("Standup", root=crm)
        c = store.create_meeting("Standup", root=crm)
        assert len({a.name, b.name, c.name}) == 3
        assert b.name.endswith("-2") and c.name.endswith("-3")

    def test_unicode_title_is_safe_on_disk(self, crm):
        d = store.create_meeting("Café ☕ review", root=crm)
        assert d.exists()
        assert store.load_meeting(d).title == "Café ☕ review"

    def test_index_rebuilds_purely_from_disk(self, crm):
        store.create_meeting("One", root=crm)
        store.create_meeting("Two", root=crm)
        index_path = store.rebuild_index(root=crm)
        index_path.unlink()                      # index is never the truth
        data = json.loads(store.rebuild_index(root=crm).read_text())
        assert data["count"] == 2

    def test_resolve_by_partial_name(self, crm):
        store.create_meeting("Acme Renewal", root=crm)
        found = store.resolve_meeting("renewal", root=crm)
        assert found is not None and "renewal" in found.name


class TestBackdatedMeetings:
    """A recording made weeks ago must file under the day it happened.

    The importer is handed the time out of the recording's own container, so
    the directory has to take its date from that rather than from the clock,
    or a July call lands in a folder named for today.
    """

    def test_started_at_dates_the_directory(self, crm):
        d = store.create_meeting("Discovery 1", root=crm,
                                 started_at="2026-08-27T08:37:16Z")
        assert d.name == "2026-08-27-discovery-1"
        assert store.load_meeting(d).started_at == "2026-08-27T08:37:16Z"

    def test_without_started_at_the_clock_still_wins(self, crm):
        today = utcnow()[:10]
        d = store.create_meeting("Standup", root=crm)
        assert d.name == f"{today}-standup"
        assert store.load_meeting(d).started_at.startswith(today)

    def test_two_backdated_meetings_the_same_day_do_not_collide(self, crm):
        a = store.create_meeting("Call", root=crm, started_at="2026-08-27T08:00:00Z")
        b = store.create_meeting("Call", root=crm, started_at="2026-08-27T09:00:00Z")
        assert a.name == "2026-08-27-call"
        assert b.name == "2026-08-27-call-2"


class TestContacts:
    def test_linking_twice_yields_one_line(self, crm):
        d = store.create_meeting("Call", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm)
        path = store.link_contact(d, "Jane Doe", root=crm)
        assert path.read_text().count("../meetings/") == 1

    def test_human_notes_below_managed_block_survive(self, crm):
        d1 = store.create_meeting("First", ["Jane Doe"], root=crm)
        path = store.link_contact(d1, "Jane Doe", root=crm)

        path.write_text(path.read_text().rstrip()
                        + "\n\nPrefers early calls.\nAllergic to slide decks.\n")

        d2 = store.create_meeting("Second", ["Jane Doe"], root=crm)
        store.link_contact(d2, "Jane Doe", root=crm)

        after = path.read_text()
        assert "Prefers early calls." in after
        assert "Allergic to slide decks." in after
        assert after.count("../meetings/") == 2

    def test_human_notes_above_managed_block_survive(self, crm):
        d = store.create_meeting("First", ["Jane Doe"], root=crm)
        path = store.link_contact(d, "Jane Doe", root=crm)
        text = path.read_text().replace("## Meetings",
                                        "Some intro the human wrote.\n\n## Meetings")
        path.write_text(text)

        d2 = store.create_meeting("Second", ["Jane Doe"], root=crm)
        store.link_contact(d2, "Jane Doe", root=crm)
        assert "Some intro the human wrote." in path.read_text()

    def test_retitled_meeting_updates_in_place(self, crm):
        d = store.create_meeting("Draft title", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm)
        meeting = store.load_meeting(d)
        meeting.title = "Real title"
        store.save_meeting(d, meeting)
        path = store.link_contact(d, "Jane Doe", root=crm)
        text = path.read_text()
        assert text.count("../meetings/") == 1
        assert "Real title" in text and "Draft title" not in text

    def test_frontmatter_fields_merge_not_clobber(self, crm):
        d = store.create_meeting("Call", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm, company="Acme")
        path = store.link_contact(d, "Jane Doe", root=crm, email="j@acme.com")
        text = path.read_text()
        assert "Acme" in text and "j@acme.com" in text


class TestVocabularyAndSearch:
    def test_vocabulary_collects_names_and_companies(self, crm):
        d = store.create_meeting("Call", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm, company="Acme")
        vocab = store.vocabulary(root=crm)
        assert "Jane Doe" in vocab and "Acme" in vocab
        assert "Jane" in vocab          # parts, so a stray surname still matches

    def test_search_finds_text_in_transcripts(self, crm):
        d = store.create_meeting("Call", root=crm)
        (d / "transcript.md").write_text("[00:00:01] **Them:** the renewal is approved")
        results = store.search("renewal", root=crm)
        assert results and "renewal" in results[0]["hits"][0]

    def test_search_returns_nothing_for_absent_term(self, crm):
        store.create_meeting("Call", root=crm)
        assert store.search("nonexistent", root=crm) == []


class TestAtomicWrite:
    def test_failed_write_leaves_original_intact(self, crm, monkeypatch):
        target = crm / "contacts" / "x.md"
        store._write_atomic(target, "original content")

        import os as os_module

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(os_module, "replace", boom)
        try:
            store._write_atomic(target, "replacement")
        except OSError:
            pass
        assert target.read_text() == "original content"
        # and no temp debris left behind
        assert not list(target.parent.glob(".tmp-*"))


class TestAtomicWriteUnderWindowsSharing:
    """A reader holding the destination open must not fail the writer.

    Found on 9 September 2026 by the Hub export, which reads every
    meeting.json while the widget is finalising one. On Windows os.replace
    onto a file another process has open raises PermissionError, so a
    perfectly ordinary concurrent read broke a write. Retrying briefly is the
    fix, and it belongs here rather than in any one reader: search, the index
    rebuild and every skill read these files too.
    """

    def test_a_transient_sharing_violation_is_retried(self, crm, monkeypatch):
        target = crm / "meetings" / "x.json"
        target.write_text("old", encoding="utf-8")

        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)

        monkeypatch.setattr(store.os, "replace", flaky)
        store._write_atomic(target, "new")
        assert target.read_text(encoding="utf-8") == "new"
        assert len(calls) == 3

    def test_it_still_raises_when_the_lock_never_clears(self, crm, monkeypatch):
        target = crm / "meetings" / "y.json"

        def always_locked(src, dst):
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(store.os, "replace", always_locked)
        with pytest.raises(PermissionError):
            store._write_atomic(target, "new")
        assert not list(target.parent.glob(".tmp-*"))


class TestUnfinishedRecordings:
    """A recording that stopped but was never transcribed must be findable.

    On 10 September a real 39-minute call landed in exactly this state: the
    recorder shut down and wrote its results, the widget's stop handler never
    ran, and the mid-call partial sat on disk wearing the frontmatter of a
    finished transcript. Nothing anywhere said so.
    """

    def _recorded(self, crm, name="Call", *, ended=True, transcribed=False):
        d = store.create_meeting(name, [], root=crm)
        (d / "mic.wav").write_bytes(b"RIFF")
        state = {"pid": 1, "started_at": 0.0}
        if ended:
            state["ended_at"] = 1.0
        (d / "recording.json").write_text(json.dumps(state), encoding="utf-8")
        if transcribed:
            m = store.load_meeting(d)
            m.transcribed = True
            store.save_meeting(d, m)
        return d

    def test_a_stopped_untranscribed_meeting_is_found(self, crm):
        d = self._recorded(crm)
        assert [p.name for p in store.unfinished(crm)] == [d.name]

    def test_one_still_recording_is_left_alone(self, crm):
        self._recorded(crm, ended=False)
        assert store.unfinished(crm) == []

    def test_a_transcribed_one_is_not_offered(self, crm):
        self._recorded(crm, transcribed=True)
        assert store.unfinished(crm) == []

    def test_a_meeting_whose_audio_is_gone_is_not_offered(self, crm):
        """mtg prune removes the wavs; there is nothing left to rescue."""
        d = self._recorded(crm)
        (d / "mic.wav").unlink()
        assert store.unfinished(crm) == []

    def test_a_meeting_that_never_recorded_here_is_not_offered(self, crm):
        store.create_meeting("Imported", [], root=crm)
        assert store.unfinished(crm) == []


class TestTheRescueDoesNotRaceTheWidget:
    """`mtg finish` and the widget both transcribe. A meeting being worked on
    looks exactly like an abandoned one — audio present, transcribed false —
    so on 10 September both ran on the same hour of audio at once."""

    def _recorded(self, crm):
        d = store.create_meeting("Call", [], root=crm)
        (d / "mic.wav").write_bytes(b"RIFF")
        (d / "recording.json").write_text(
            json.dumps({"pid": 1, "started_at": 0.0, "ended_at": 1.0}),
            encoding="utf-8")
        return d

    def test_a_meeting_being_transcribed_is_not_offered(self, crm):
        from notetaker import transcribe as tr
        d = self._recorded(crm)
        assert store.unfinished(crm)
        (d / tr.WORKING_FILE).write_text("999", encoding="utf-8")
        assert store.unfinished(crm) == []

    def test_it_is_offered_again_once_the_marker_clears(self, crm):
        from notetaker import transcribe as tr
        d = self._recorded(crm)
        (d / tr.WORKING_FILE).write_text("999", encoding="utf-8")
        assert store.unfinished(crm) == []
        (d / tr.WORKING_FILE).unlink()
        assert [p.name for p in store.unfinished(crm)] == [d.name]

    def test_a_marker_from_a_dead_process_does_not_block_forever(self, crm, monkeypatch):
        from notetaker import transcribe as tr
        d = self._recorded(crm)
        (d / tr.WORKING_FILE).write_text("999", encoding="utf-8")
        marker = d / tr.WORKING_FILE
        old = time.time() - tr.WORKING_STALE_SECONDS - 10
        os.utime(marker, (old, old))
        assert [p.name for p in store.unfinished(crm)] == [d.name]


class TestEmptyRecords:
    """Four meetings arrived from a Fathom import holding a meeting.json and
    nothing else. They inflate every count, can never be given a lane because
    there is nothing to derive one from, and sat unnoticed until someone went
    looking for why `mtg lane` never emptied."""

    def test_a_record_with_no_audio_and_no_transcript_is_reported(self, crm):
        d = store.create_meeting("Impromptu Teams Meeting", [], root=crm)
        assert [p.name for p in store.empty_records(crm)] == [d.name]

    def test_a_transcribed_meeting_is_not(self, crm):
        d = store.create_meeting("Real", [], root=crm)
        (d / "transcript.md").write_text("[00:00:01] **Them:** hello", encoding="utf-8")
        assert store.empty_records(crm) == []

    def test_one_still_holding_audio_is_not(self, crm):
        d = store.create_meeting("Recorded", [], root=crm)
        (d / "mic.wav").write_bytes(b"RIFF")
        assert store.empty_records(crm) == []

    def test_one_written_up_by_hand_is_not(self, crm):
        """An imported summary with no transcript is still a real record."""
        d = store.create_meeting("Imported", [], root=crm)
        (d / "notes.md").write_text("# Notes\n\nFrom Fathom.\n", encoding="utf-8")
        assert store.empty_records(crm) == []
