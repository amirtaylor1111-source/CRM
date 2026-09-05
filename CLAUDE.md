# CRM and meeting notetaker

A local, consent-first meeting recorder whose output you write up. Capture
and transcription run on the user's Windows laptop; everything intelligent
happens here, in a normal Claude Code session.

## The constraint that shapes everything

**No paid API.** Nothing in this repo may call the Anthropic API, import the
`anthropic` package, or read an API key. The user's whole reason for building
this rather than paying for Fathom is that summarisation should come out of
their existing Claude Code subscription. Local code captures, transcribes and
stores; you do the rest by reading files.

If you are ever tempted to add an API call to automate the write-up, do not.
That is the one thing this design rules out.

## Layout

```
meetings/<YYYY-MM-DD>-<slug>/
    meeting.json      participants, timings, consent record
    mic.wav           the user's voice          (gitignored)
    system.wav        everyone else             (gitignored)
    transcript.md     machine-authored          <- read this
    transcript.json   segments, timings, confidence
    notes.md          yours                     <- write this
meetings/index.json   rollup, rebuildable from disk
contacts/<slug>.md    frontmatter + managed meeting list + human notes
notetaker/            the Python tool
```

## Who authors what

| File | Author | Rule |
|---|---|---|
| `transcript.md` / `.json` | the machine | **never edit** — its value is being unmodified |
| `notes.md` | you | free to rewrite |
| `contacts/*.md` between `## Meetings` and `<!-- /meetings -->` | the tool | edit via `store.link_contact` |
| everything else in a contact file | the human | **never clobber** |

The contact-file rule matters. People keep hand-written notes in those files.
Splice into the managed block; do not rewrite the file wholesale.

## Two tracks

Audio is recorded as two files, so `mic.wav` is the user and `system.wav` is
everyone else. Speaker labels in the transcript come from that, not from a
diarisation model, so they are reliable even where the words are not.

Segments marked `⚠` were low-confidence. Treat their content as uncertain.

## Accuracy, and your job

The transcript is roughly 92–97% accurate at the word level. Your notes
should be effectively correct, because you can repair errors from context and
the transcript cannot. Fix mangled names against the participant list. Never
invent an action item that was not agreed — that is the failure mode that
actually costs the user something.

## Commands

The user runs `mtg start` / `mtg stop` in a terminal. In here:

- `/notes [meeting]` — write up a meeting (the `meeting-notes` skill)
- `/prep <person>` — pre-call briefing from history
- `/followup [meeting]` — draft the follow-up email
- `/calendar` — sync upcoming meetings from Outlook
- `/import-fathom` — pull history out of Fathom
- `/dealroom <company>` — client-facing page assembled from the CRM

Phone calls arrive via `mtg phone <folder>`, which imports Samsung's own call
recordings. Those are single-track, so everything is labelled as the caller;
do not attribute lines between speakers in a phone-call transcript the way
you would for a two-track laptop meeting.

## Connectors belong in the session, not in the code

Fathom, Outlook and anything else with credentials are reached by you, here,
using MCP tools. The Python side only ever reads a JSON file you have
written. That keeps the no-API rule intact, keeps every import path testable
with no network, and means the tool still works on a machine with no
connectors configured.

When you sync or import, write the JSON to a temp file and call the CLI. Do
not reach into `meetings/` and write files yourself — `store.py` handles slug
collisions, idempotency and the managed contact block, and hand-written files
will get those wrong.

## Names are the thing worth getting right

`store.vocabulary()` feeds the transcript name corrector, so every contact
you add improves every future transcript. When a calendar address resolves to
someone the CRM does not know, say so. When two sources disagree about a
name, the calendar wins — the person typed their own address into it.

## Working on the tool itself

```bash
python3 -m pytest tests/ -q
```

Modules must import on a machine with no audio libraries, no ffmpeg and no
speech model installed, because `mtg doctor` has to run on exactly that
machine to tell the user what is missing. Keep optional imports lazy and
guarded.
