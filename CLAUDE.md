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

## Working on the tool itself

```bash
python3 -m pytest tests/ -q
```

Modules must import on a machine with no audio libraries, no ffmpeg and no
speech model installed, because `mtg doctor` has to run on exactly that
machine to tell the user what is missing. Keep optional imports lazy and
guarded.
