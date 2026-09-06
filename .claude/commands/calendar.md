---
description: Sync upcoming meetings from Outlook so the recorder knows what is next
---

Sync the calendar: $ARGUMENTS

The recorder has no way to know a meeting is starting, because nothing joins
the call. This closes that gap.

1. Search the Outlook calendar for events from now to two weeks out.
2. Build a JSON array. Times must be ISO 8601 with an explicit offset —
   convert the `dateTime`/`timeZone` pair the connector returns into UTC and
   suffix `Z`. Getting this wrong makes `mtg start --next` pick the wrong
   meeting, so be careful with it.

```json
[{
  "subject": "Aged-Marco Chat",
  "start": "2026-09-18T11:00:00Z",
  "end": "2026-09-18T11:30:00Z",
  "attendees": ["mfavero@solugrowth.com", "montysmythe@outlook.com"],
  "organizer": "amir@agedventures.co.za",
  "location": "Microsoft Teams Meeting"
}]
```

3. Write it to `/tmp/calendar.json` and run
   `.venv\Scripts\python.exe -m notetaker.cli calendar /tmp/calendar.json`.

Skip cancelled events and all-day entries — neither is a call to record.

## While you are here

Attendee addresses the CRM has never seen are an opportunity. If an address
appears that has no `contacts/<slug>.md`, say so and offer to create one.
Every contact added improves transcript accuracy, because their name joins
the vocabulary that corrects mis-transcriptions.

If an address resolves to a contact whose name looks wrong — a transcript
guessed at it, or two records describe the same person — raise it rather than
silently keeping both. The calendar is the more reliable source, since the
person typed their own address into it.
