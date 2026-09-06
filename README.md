# Meeting notetaker

Records your meetings locally, transcribes them on your own machine, and
hands the transcript to Claude Code to write up. Nothing joins your call and
there is no subscription.

## Using it

The widget is a pill at the bottom right of the screen. Expanded, it holds
the consent line to read out, the next steps agreed so far, the questions
worth asking before the call ends, what the CRM already has on the person you
are talking to, and a box for asking your own questions. It is hidden from
screen sharing, so none of it shows in a shared window.

<!-- The screenshots in docs/img/ show the old browser window and need re-taking. -->

The widget sits at the bottom right of your screen from login, as a small
strip showing your next meeting. Two minutes before a calendar meeting it
expands with everything filled in; it only offers, it never starts recording
on its own. It shows you the sentence to say out loud and stays greyed out
until you flip the switch that says you have said it. Then one button
starts, and the same button stops.

While the call runs, the widget listens along. It transcribes as you go, and
every couple of minutes of talk it asks Claude Code, on your subscription,
for what has been agreed so far and what is worth asking before the call
ends. A panel shows what you already know about the person from earlier
calls, and an ask box answers questions about the meeting, remembering the
conversation. The widget is hidden from screen sharing, so none of that
appears if you share your screen.

When you press Stop the transcript is done within seconds and the write-up
runs at once; the widget floats with the notes, the next steps and the
follow-up questions. That automatic write-up produces `notes.md`; updating
contact files is left to `/notes` in a session where you can see the change.
Close the widget and the recording keeps going; it is its own process, and
the widget picks it straight back up.

That is the whole loop. Everything below is for when you want more control.

The widget is a small local page in a window Python owns (WebView2, which
Windows ships), talking to a small local server; nothing is exposed beyond
your own machine and every request carries a per-launch token. `mtg app
--browser` opens the same page in an Edge window instead, without the
always-on-top and screen-share protection, and `mtg app --classic` opens a
plainer built-in window if there is no Chromium-based browser at all.

Claude Code needs to have been logged in from a terminal once for the live
panels and the automatic write-up: run `claude`, then `/login`. Until then
the widget records and transcribes, and says so.

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
| The widget's live panels and ask box | Claude Code, run headlessly | included |

There is no API key anywhere in this repo, and no code here calls a paid
service. The intelligence happens when Claude Code reads a file, in a normal
session or run headlessly by the widget, which your subscription already
covers. Each brief, answer and write-up is a turn on that plan; the widget
briefs after every two minutes of new speech, so an hour's call is about
thirty turns.

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
| `mtg phone <folder>` | import call recordings from your phone |
| `mtg doctor` | check setup, show which model your machine will use |
| `mtg prune` | delete audio from meetings already transcribed |

In Claude Code: `/notes` to write up, `/prep <person>` for a pre-call
briefing, `/followup` to draft the email, `/calendar` to sync Outlook,
`/import-fathom` to pull history out of Fathom, `/dealroom <company>` to
build a client-facing page from the history. `/live-brief <meeting>` and
`/ask <meeting> <question>` are what the widget runs for you during a call.

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

## Phone calls

Your phone can record its own cellular calls, and `mtg phone` brings them in
and transcribes them like any other meeting. See
[docs/phone-calls.md](docs/phone-calls.md).

WhatsApp calls cannot be recorded by any app on any phone — Android excludes
voice-call audio from the capture API deliberately, and iOS has no such API
at all. Take those on WhatsApp Desktop instead, where the laptop recorder
handles them exactly like Teams.

## What it does not do

- **Nothing joins your call.** There is no bot in the participant list, which
  also means no auto-join. You start the recording yourself.
- **Transcription runs alongside the call**, about thirty seconds behind,
  and is finished within seconds of Stop. Speech costs roughly a third of a
  core while someone is talking; silence costs nothing.
- **It is not 100% accurate**, and neither is anything else. See
  [docs/accuracy.md](docs/accuracy.md) for real numbers.

## Setup

Windows: [docs/setup-windows.md](docs/setup-windows.md). It is one script.

## Consent

The tool asks you to confirm you have told the other participants before it
records, and stores that confirmation in `meeting.json`. There is a suggested
form of words in [docs/consent.md](docs/consent.md).
