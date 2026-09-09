# CRM and meeting notetaker

> **Running on Amir's Windows laptop for the first time?** Read
> [HANDOFF.md](HANDOFF.md) first — it is a short, finite job, and it is
> not "continue building".

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

%LOCALAPPDATA%\mtg\exports\meetings.json   what Hub reads    <- we write
<hub repo>/data/exports/organisations.json  what Hub writes   <- we read
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

The user records from the widget (or `mtg start` / `mtg stop` in a
terminal). In here:

- `/notes [meeting]` — write up a meeting (the `meeting-notes` skill)
- `/prep <person>` — pre-call briefing from history
- `/followup [meeting]` — draft the follow-up email
- `/calendar` — sync upcoming meetings from Outlook
- `/import-fathom` — pull history out of Fathom
- `/dealroom <company>` — client-facing page assembled from the CRM
- `/live-brief <meeting>` and `/ask <meeting> <question>` — what the widget
  runs headlessly during and after a call; fine to run by hand too

And two on the command line: `mtg export-hub` rebuilds the export Hub reads,
and `mtg lane <meeting> <business|personal|unknown>` corrects the lane the
export guessed.

## The widget runs you headlessly

The always-on-top widget (`notetaker/widget.py`) runs Claude Code itself,
`claude -p` in this folder, for four things: `/prep` when a call starts,
`/live-brief` every couple of minutes of speech, `/ask` for its ask box, and
`/notes` the moment a call's transcript is finished. That is the same
subscription as this session, not an API. When you are run that way you
have Read, Glob, Grep and Skill, and for `/notes` the right to write
`notes.md` and the participant list in `meeting.json`; never a contact file,
never a transcript, never Bash. Contact files hold the user's own notes and
a transcript can contain anything a caller chose to say, so the CRM update
in the meeting-notes skill is left to an interactive `/notes`, where the
user sees the change. A transcript whose frontmatter says `live: True` is
still being written: treat it as a partial record, not the meeting.

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

## Hub reads our meetings, and we do not write into Hub

`notetaker/hubexport.py` writes `meetings.json` for Hub's collector, rebuilt
whole every time a write-up lands. The contract is
`docs/superpowers/specs/2026-09-09-meetings-to-hub.md`, agreed with the Hub
session on 9 September and changed only by agreement. One writer per file: we
write that one and only read Hub's.

Two rules in it are load-bearing and will look like oversights to anyone who
did not read the argument:

**The transcript goes as a path, never as text.** Hub indexes what it stores
and feeds it to prompts. A 92-97% accurate transcript would put words nobody
said into that index and let Hub read a mis-transcribed figure as fact.
`notes.md` is where those errors are already repaired, so it is the more
accurate artifact and it is what travels.

**`lane` is three-valued and never guesses.** `business`, `personal` or
`unknown`. Filing a personal conversation as business puts Amir's own
finances into Hub's business surfaces; saying `unknown` costs a search miss.
Those are not the same size of mistake.

## Names are the thing worth getting right

`store.vocabulary()` feeds the transcript name corrector, so every contact
you add improves every future transcript. When a calendar address resolves to
someone the CRM does not know, say so. When two sources disagree about a
name, the calendar wins — the person typed their own address into it.

## Decisions live in docs/superpowers/, and only there

`specs/` for agreed interfaces, `plans/` for work designed but not built,
`spikes/` for questions answered including the ones answered "no". Read all
three before proposing anything: several of them record capabilities this
repo already has, and a decision recorded only in a commit message is a
decision that gets re-proposed.

There is a test pinning this. Until 9 September the spikes were split across
`docs/spikes/` and `docs/superpowers/spikes/`, and a peer session proposed
speaker diarization for phone calls that had already been spiked three days
earlier with a better implementation. It had read `docs/superpowers/` and
reasonably believed it had seen everything. A convention that is only mostly
true is worse than none, because it is trusted.

## Working on the tool itself

```bash
.venv\Scripts\python.exe -m pytest tests -q
```

Modules must import on a machine with no audio libraries, no ffmpeg and no
speech model installed, because `mtg doctor` has to run on exactly that
machine to tell the user what is missing. Keep optional imports lazy and
guarded.
