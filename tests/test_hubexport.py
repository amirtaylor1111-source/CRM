"""The export Hub reads.

The contract is docs/superpowers/specs/2026-09-09-meetings-to-hub.md. These
tests are this repo's half of it: a change here that would break Hub fails
here rather than silently in that repository.
"""
import json

import pytest

from notetaker import hubexport, store

NOTES = """# Discovery 1

**Date:** 2026-08-27 · **Duration:** 9m · **Present:** Kayleigh Adams

## TL;DR

- They want a pilot before committing.
- Budget is roughly twenty thousand a month.

## Decisions

- Pilot agreed, starting October.
- Pricing stays as quoted.

## Action items

- [ ] **@me** — send the revised pricing (due: 2026-09-01)
- [x] **@Kayleigh** — confirm the technical contact (due: unspecified)

## Notable quotes

> "We do the pilot." — Kayleigh [00:00:00]
"""

TRANSCRIPT = """---
engine: nemo-parakeet-tdt-0.6b-v3
expected_accuracy: 6.3%
tracks: system
segments: 128
low_confidence_segments: 3
names_corrected: 0
speaker_method: separate audio tracks (attribution is exact)
live: False
---

**Them** [00:00:00] Garbled ASR only ever seen in the transcript.
"""


def meeting_with(crm, *, title="Discovery 1", participants=(), notes=None,
                 transcript=None, **extra):
    directory = store.create_meeting(title, participants, consent_obtained=True,
                                     root=crm, started_at="2026-08-27T08:37:16Z")
    if notes is not None:
        (directory / "notes.md").write_text(notes, encoding="utf-8")
    if transcript is not None:
        (directory / "transcript.md").write_text(transcript, encoding="utf-8")
    if extra:
        data = json.loads((directory / "meeting.json").read_text(encoding="utf-8"))
        data.update(extra)
        (directory / "meeting.json").write_text(json.dumps(data), encoding="utf-8")
    return directory


class TestTheEnvelope:
    def test_an_empty_crm_still_exports_a_valid_file(self, crm):
        doc = hubexport.build(root=crm)
        assert doc["meetings"] == []
        assert doc["schemaVersion"] == 1
        assert doc["writtenAt"].endswith("Z")

    def test_every_id_appears_once(self, crm):
        meeting_with(crm, title="Same Name")
        meeting_with(crm, title="Same Name")
        ids = [m["id"] for m in hubexport.build(root=crm)["meetings"]]
        assert len(ids) == len(set(ids)) == 2


class TestTheRecord:
    def test_a_meeting_with_no_write_up_is_still_exported(self, crm):
        """Hub learns the meeting happened, which is the fact that ages fastest."""
        meeting_with(crm)
        record = hubexport.build(root=crm)["meetings"][0]
        assert record["title"] == "Discovery 1"
        assert record["notes"] == ""
        assert record["summary"] == ""
        assert record["decisions"] == []
        assert record["actionItems"] == []
        assert record["notesPath"] is None

    def test_the_write_up_is_carried_whole(self, crm):
        meeting_with(crm, notes=NOTES)
        record = hubexport.build(root=crm)["meetings"][0]
        assert record["notes"] == NOTES
        assert record["notesPath"].endswith("notes.md")

    def test_the_summary_comes_from_the_tldr(self, crm):
        meeting_with(crm, notes=NOTES)
        summary = hubexport.build(root=crm)["meetings"][0]["summary"]
        assert "want a pilot" in summary
        assert "twenty thousand" in summary
        assert "Decisions" not in summary

    def test_decisions_are_listed(self, crm):
        meeting_with(crm, notes=NOTES)
        decisions = hubexport.build(root=crm)["meetings"][0]["decisions"]
        assert decisions == ["Pilot agreed, starting October.",
                             "Pricing stays as quoted."]

    def test_action_items_carry_owner_due_and_done(self, crm):
        meeting_with(crm, notes=NOTES)
        actions = hubexport.build(root=crm)["meetings"][0]["actionItems"]
        assert actions[0] == {"text": "send the revised pricing",
                              "assignee": "@me", "done": False,
                              "due": "2026-09-01"}
        assert actions[1]["assignee"] == "@Kayleigh"
        assert actions[1]["done"] is True
        assert actions[1]["due"] is None


class TestTheTranscriptIsNeverInlined:
    def test_metadata_travels_and_text_does_not(self, crm):
        meeting_with(crm, notes=NOTES, transcript=TRANSCRIPT)
        record = hubexport.build(root=crm)["meetings"][0]
        assert record["transcript"]["engine"] == "nemo-parakeet-tdt-0.6b-v3"
        assert record["transcript"]["lowConfidenceSegments"] == 3
        assert record["transcriptPath"].endswith("transcript.md")
        assert "Garbled ASR" not in json.dumps(record)
        assert record["notes"] == NOTES  # the quote in the notes survives

    def test_a_live_transcript_is_flagged_partial(self, crm):
        meeting_with(crm, transcript=TRANSCRIPT.replace("live: False", "live: True"))
        record = hubexport.build(root=crm)["meetings"][0]
        assert record["transcript"]["partial"] is True

    def test_a_meeting_with_no_transcript_says_so(self, crm):
        meeting_with(crm)
        record = hubexport.build(root=crm)["meetings"][0]
        assert record["transcriptPath"] is None
        assert record["transcript"]["partial"] is False


class TestLane:
    """Three-valued on purpose. Guessing business on thin evidence is the
    failure that costs Amir something; saying 'unknown' costs a search miss."""

    def test_named_participants_make_it_business(self, crm):
        meeting_with(crm, participants=["Kayleigh Adams"])
        assert hubexport.build(root=crm)["meetings"][0]["lane"] == "business"

    def test_the_personal_callout_wins_over_participants(self, crm):
        meeting_with(crm, participants=["Eitan Dubb"],
                     notes="# X\n\n> **Personal, not client work.** Career chat.\n")
        assert hubexport.build(root=crm)["meetings"][0]["lane"] == "personal"

    def test_nothing_to_go_on_is_unknown_not_business(self, crm):
        meeting_with(crm, title="Impromptu Microsoft Teams Meeting")
        assert hubexport.build(root=crm)["meetings"][0]["lane"] == "unknown"

    def test_an_explicit_lane_beats_every_heuristic(self, crm):
        meeting_with(crm, participants=["Kayleigh Adams"], lane="personal")
        assert hubexport.build(root=crm)["meetings"][0]["lane"] == "personal"


class TestRevision:
    """Advisory: Hub computes its own and logs a mismatch. It still has to
    mean something, which is that it moves with what Hub stores and nothing
    else."""

    def rev(self, crm):
        return hubexport.build(root=crm)["meetings"][0]["revision"]

    def test_it_is_stable_across_runs(self, crm):
        meeting_with(crm, notes=NOTES)
        assert self.rev(crm) == self.rev(crm)

    def test_editing_the_write_up_moves_it(self, crm):
        directory = meeting_with(crm, notes=NOTES)
        before = self.rev(crm)
        (directory / "notes.md").write_text(NOTES + "\n- and one more thing\n",
                                            encoding="utf-8")
        assert self.rev(crm) != before

    def test_re_transcribing_does_not_move_it(self, crm):
        """The transcript block is not stored by Hub, so churning it must not
        churn Hub's rows."""
        directory = meeting_with(crm, notes=NOTES, transcript=TRANSCRIPT)
        before = self.rev(crm)
        (directory / "transcript.md").write_text(
            TRANSCRIPT.replace("names_corrected: 0", "names_corrected: 4"),
            encoding="utf-8")
        assert self.rev(crm) == before

    def test_reordering_participants_does_not_move_it(self, crm):
        directory = meeting_with(crm, participants=["Ann Blue", "Bob Green"],
                                 notes=NOTES)
        before = self.rev(crm)
        data = json.loads((directory / "meeting.json").read_text(encoding="utf-8"))
        data["participants"].reverse()
        (directory / "meeting.json").write_text(json.dumps(data), encoding="utf-8")
        assert self.rev(crm) == before

    def test_changing_the_lane_moves_it(self, crm):
        directory = meeting_with(crm, participants=["Kayleigh Adams"], notes=NOTES)
        before = self.rev(crm)
        data = json.loads((directory / "meeting.json").read_text(encoding="utf-8"))
        data["lane"] = "personal"
        (directory / "meeting.json").write_text(json.dumps(data), encoding="utf-8")
        assert self.rev(crm) != before


class TestWritingTheFile:
    def test_it_round_trips_through_disk(self, crm, tmp_path):
        meeting_with(crm, notes=NOTES, transcript=TRANSCRIPT)
        path = hubexport.write(tmp_path / "exports" / "meetings.json", root=crm)
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["meetings"][0]["notes"] == NOTES

    def test_no_partial_file_is_left_when_writing_fails(self, crm, tmp_path,
                                                        monkeypatch):
        """A reader must never see half a file."""
        destination = tmp_path / "exports" / "meetings.json"
        meeting_with(crm, notes=NOTES)
        hubexport.write(destination, root=crm)
        good = destination.read_text(encoding="utf-8")

        monkeypatch.setattr(hubexport, "build",
                            lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            hubexport.write(destination, root=crm)
        assert destination.read_text(encoding="utf-8") == good
        assert not list(destination.parent.glob("*.writing"))


class TestTheShapeHubRelieson:
    """The vendored half of the contract. If this fails, Hub's collector
    breaks, and it should be found here."""

    REQUIRED = {"id", "revision", "date", "endedAt", "title", "lane",
                "participants", "summary", "topics", "decisions", "actionItems",
                "notes", "notesPath", "transcriptPath", "transcript", "consent",
                "project"}

    def test_every_documented_field_is_present(self, crm):
        meeting_with(crm, notes=NOTES, transcript=TRANSCRIPT)
        assert set(hubexport.build(root=crm)["meetings"][0]) == self.REQUIRED

    def test_participants_are_plain_names(self, crm):
        """Hub's collector maps names, not objects."""
        meeting_with(crm, participants=["Kayleigh Adams"])
        record = hubexport.build(root=crm)["meetings"][0]
        assert record["participants"] == ["Kayleigh Adams"]

    def test_timestamps_are_utc_iso(self, crm):
        meeting_with(crm)
        record = hubexport.build(root=crm)["meetings"][0]
        assert record["date"] == "2026-08-27T08:37:16Z"

    def test_it_imports_without_audio_libraries(self):
        """mtg doctor has to run on a machine with none of them."""
        import importlib
        importlib.reload(hubexport)


class TestFindingTheUnknowns:
    """Hub does not file an `unknown` meeting at all, so a meeting left
    unknown is invisible to Hub rather than merely uncategorised. That makes
    the list of them something the tool has to offer, not something Amir has
    to know to go looking for."""

    def test_it_lists_only_the_undecided_ones(self, crm):
        meeting_with(crm, title="With People", participants=["Kayleigh Adams"])
        meeting_with(crm, title="Impromptu One")
        meeting_with(crm, title="Impromptu Two")
        unknown = hubexport.undecided(root=crm)
        assert [m["title"] for m in unknown] == ["Impromptu One", "Impromptu Two"]

    def test_setting_a_lane_removes_it_from_the_list(self, crm):
        directory = meeting_with(crm, title="Impromptu One")
        assert len(hubexport.undecided(root=crm)) == 1
        meeting = store.load_meeting(directory)
        meeting.lane = "business"
        store.save_meeting(directory, meeting)
        assert hubexport.undecided(root=crm) == []
