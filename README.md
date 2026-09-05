# Meeting notetaker

Records your meetings locally, transcribes them on your own machine, and
hands the transcript to Claude Code to write up. Nothing joins your call and
there is no subscription.

## Using it

Double-click **Meeting Notetaker** on your desktop.

The window fills in the meeting from your calendar, shows you the sentence to
say out loud, and stays greyed out until you flip the switch that says you
have said it. Then one button starts, and the same button stops. It
transcribes on its own, the button turns green when it is done, and **Write
up notes in Claude** opens Claude Code with the command already typed.

You can close the window at any point. The recording is its own process and
keeps going; reopen the app and it picks the recording straight back up.
Two minutes before a calendar meeting, the app opens itself with everything
filled in — it only offers, it never starts recording on its own.

That is the whole loop. Everything below is for when you want more control.

The window is HTML running in Edge's app mode, talking to a small local
server. Nothing is exposed beyond your own machine, every request carries a
per-launch token, and the server exits when the window closes. If you have no
Chromium-based browser at all, `mtg app --classic` opens a plainer built-in
window that does the same job.

### From a terminal, if you prefer

```
mtg start --next     # title and attendees from your calendar
   ... have the meeting ...
mtg stop             # stops, then transcribes
```

The app and the commands drive exactly the same code; neither is a wrapper
around the other.

## Why it costs nothing

| Stage | Runs on | Cost |
|---|---|---|
| Capture | your machine | free |
| Transcription | your machine, offline | free |
| Notes, briefings, follow-ups | Claude Code, your existing plan | included |

There is no API key anywhere in this repo, and no code here calls a paid
service. The intelligence happens when Claude reads a file during a normal
session, which your subscription already covers.

## What it produces

```
meetings/2026-09-05-acme-renewal/
    meeting.json      who, when, and the consent record
    mic.wav           you
    system.wav        everyone else
    transcript.md     machine-authored, timestamped, never hand-edited
    transcript.json   segments with timings and confidence
    notes.md          Claude-authored write-up
contacts/jane-doe.md  managed meeting list + your own free-form notes
```

Transcripts and notes are committed to git. Audio is not, because it is large
and reproducible into the transcript that matters.

## Commands

| | |
|---|---|
| `mtg start` | begin recording, after confirming disclosure |
| `mtg stop` | stop and transcribe |
| `mtg status` | is anything recording, and for how long |
| `mtg list` | recent meetings |
| `mtg search <term>` | across every transcript and note |
| `mtg next` | upcoming meetings, and which one is recordable now |
| `mtg start --next` | start recording, title and attendees from the calendar |
| `mtg doctor` | check setup, show which model your machine will use |
| `mtg prune` | delete audio from meetings already transcribed |

In Claude Code: `/notes` to write up, `/prep <person>` for a pre-call
briefing, `/followup` to draft the email, `/calendar` to sync Outlook,
`/import-fathom` to pull history out of Fathom, `/dealroom <company>` to
build a client-facing page from the history.

Set `MTG_ME` to your own email address so you are not listed as an attendee
of your own meetings.

## The calendar loop

Nothing joins your calls, so the tool cannot know a meeting has started. A
synced calendar closes most of that gap:

```
/calendar              # in Claude Code, once a week
mtg next               # what is coming up
mtg start --next       # title and attendees filled in for you
```

`--next` picks the meeting already running, or one starting within fifteen
minutes, so you rarely have to name it.

## Two tracks, not one

Your microphone and the incoming call audio are recorded to separate files.
This matters more than the choice of model. Speaker attribution becomes a
property of which file the audio was in, rather than a guess, and each track
transcribes more accurately without the other side talking over it.

**This only works if you wear headphones.** On speakers the remote voices
leak into your microphone, both tracks contain both parties, and the
advantage disappears.

## What it does not do

- **Nothing joins your call.** There is no bot in the participant list, which
  also means no auto-join. You start the recording yourself.
- **Transcription happens after the meeting**, not live. On a mid-range
  laptop a one-hour call takes five to ten minutes.
- **It is not 100% accurate**, and neither is anything else. See
  [docs/accuracy.md](docs/accuracy.md) for real numbers.

## Setup

Windows: [docs/setup-windows.md](docs/setup-windows.md). It is one script.

## Consent

The tool asks you to confirm you have told the other participants before it
records, and stores that confirmation in `meeting.json`. There is a suggested
form of words in [docs/consent.md](docs/consent.md).
