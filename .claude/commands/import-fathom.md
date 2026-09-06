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

## Pass 2 — transcripts

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
