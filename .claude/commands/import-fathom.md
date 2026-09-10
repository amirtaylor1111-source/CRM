---
description: Pull meeting history out of Fathom into this CRM
---

Import meetings from Fathom into this repo: $ARGUMENTS

This rescues history from a service the user is leaving. Do it in two passes
so a large history does not have to be held in one go.

## Pass 1 — the skeleton

1. `list_meetings` with `max_pages: 10` to get everything. Note each
   meeting's `recording_id`, `url`, title, date, and `calendar_invitees`.
2. Build a JSON array where each entry is:

```json
{
  "title": "SCG Corporate - Branded Calling Discussion",
  "date": "2026-07-31",
  "source": "fathom",
  "source_id": "169072944",
  "source_url": "https://fathom.video/calls/766143761",
  "participants": [{"name": "Ian Boyce"}, {"name": "Sean Shuker"}]
}
```

3. Write it to `/tmp/fathom-import.json` and run
   `.venv\Scripts\python.exe -m notetaker.cli import /tmp/fathom-import.json`.

This alone is worth doing immediately: it creates a contact file per person,
which populates the vocabulary that corrects names in every future
transcript.

Where an invitee is only an email address, use the part before the `@` as the
name and record the email. Do not invent a full name.

## Pass 1 leaves records of nothing until pass 2 runs

Say this to the user before starting, and again when pass 1 finishes.

A skeleton is a `meeting.json` and no content. It counts as a meeting
everywhere — in `meetings/index.json`, in `/prep`, in the Hub export, in any
measurement of how big the corpus is — while containing nothing at all.

On this repo, pass 1 ran and pass 2 never did. **Eighteen of thirty meetings
were skeletons for six weeks** and nobody noticed, because a list of thirty
meetings looks exactly like a list of thirty meetings. It was found only when
someone asked why `mtg lane` never emptied.

So: **never finish an import at the end of pass 1.** If the user does not want
every transcript, still bring across every *summary* — Fathom returns them
from `list_meetings` with `include_summary: true`, one call for the lot, and a
summary in `notes.md` is the difference between a record and a record of
nothing.

`mtg doctor` reports meetings with no audio and no transcript. Check it after
an import and expect zero.

## Pass 2 — summaries for everything, transcripts for what matters

Summaries first, because they are cheap and they are what stops a skeleton
being empty. `list_meetings` with `include_summary: true` and `max_pages: 3`
returns them all at once.

Write each into `meetings/<id>/notes.md` with a header that says what it is:
imported from Fathom rather than written from a recording, no transcript
behind it in this repo, and therefore missing the timestamps and verbatim
quotes a normal write-up carries. Add the meeting's `source_url` so the full
version is one click away.

Warn in that header that Fathom's summaries state invented detail as
confidently as real detail. On the one call recorded both ways, Fathom's
summary named a system nobody mentioned and produced an action item for a
topic that never came up.

## Pass 3 — transcripts

Transcripts are large, so fetch at most three per run. Ask the user which
meetings matter, or default to the most recent five.

For each: `get_meeting_transcript` with the `recording_id` and `url`, then
re-import that single meeting with `transcript_md` filled in. Re-importing is
idempotent — matching on `source_id`, it updates the existing folder rather
than creating a second copy.

## Afterwards

Report how many meetings and contacts landed, and which meetings still have
no transcript. Suggest `/notes <meeting>` for any that are worth writing up.

Never invent participants, dates or content. If Fathom has no value for a
field, leave it empty.
