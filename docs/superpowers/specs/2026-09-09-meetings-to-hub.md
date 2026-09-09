# Interface: meetings from the notetaker to Hub

**9 September 2026.** The notetaker half is built and tested
(`notetaker/hubexport.py`, `tests/test_hubexport.py`). The Hub collector is
not. Revised the same day after Hub argued with it; the revision
section records what changed and which of us was wrong.

Authored by the CRM notetaker session. The Hub side is Hub's to write; this
file specifies only what the notetaker guarantees to produce and what Hub
needs from it.

## What this is for

Hub is Amir's desktop CRM assistant. It already has `source: 'meeting'` as a
first-class message type and an `ops` collector that reads meetings off disk.
Nothing points it at the notetaker, so the meetings Amir actually records,
and the write-ups Claude produces from them, are invisible to the assistant
whose job is to know what is going on.

Amir asked for the two to be connected. He has said Hub may see everything.

## Direction and mechanism

The notetaker writes a file. Hub reads it. No HTTP, no write route into Hub,
no shared database, no process needs the other to be running.

This mirrors the link that already exists in the opposite direction: Hub
writes `organisations.json` for the notetaker's transcription vocabulary. One
file per direction, each app writing only inside its own data directory and
reading the other's, keeps a single pattern across the estate.

Rejected alternatives:

- **An HTTP write route into Hub.** Hub's bearer token is built, but its
  CLAUDE.md defers the first write route to plan 1B, and this does not need
  one. Two desktop apps that are frequently not running at the same time
  should not depend on each other being up.
- **Pointing Hub's existing `ops` collector at this repo.** It would couple
  Hub to the notetaker's on-disk layout, and the shapes do not match:
  `meetings/index.json` has no summary, no decisions and no action items,
  because those live in `notes.md` as prose that only Claude writes.

## The file

Path: `%LOCALAPPDATA%\mtg\exports\meetings.json`

`notetaker/log.py` already establishes `%LOCALAPPDATA%\mtg` as this tool's
data directory. Written through a temporary file and renamed into place, so a
reader never sees a partial file. Same technique Hub uses for its own export.

**Always a full rebuild from what is on disk.** Never incremental, never a
delta. There is no cursor to corrupt, no partial state to reconcile, and a
deleted export file costs nothing because the next run recreates it whole.
This is the same reasoning `store.rebuild_index` already uses, and Hub's hash
cursor makes re-reading an unchanged file free.

Rebuilding does not mean the file is authoritative about absence. See
"Deletion" below.

```json
{
  "writtenAt": "2026-09-09T14:02:11Z",
  "note": "Meetings from Amir's local notetaker. Notes are Claude-authored and error-repaired; transcripts are machine-authored and are referenced by path, never inlined.",
  "schemaVersion": 1,
  "meetings": [ ... ]
}
```

## One writer, everyone else reads

The notetaker is the **sole writer** of `meetings.json`. Hub reads it and
never writes it, exactly as Hub owns `organisations.json` and the notetaker
will only ever read that. No third party writes either file.

This is the same rule as the Hub and Mini CRM publish contract: one writer,
everyone else reads, changed only by agreement. It is stated because the
failure it prevents is quiet. Two writers to one file produce a corruption
that looks like a parsing bug in the reader, and it is found days later by
whoever is least equipped to recognise it.

The canonical copy of this spec lives in this repo, because this repo owns
the producer. Hub vendors it. The pair carries a hash and a self-test that
fails on drift.

## What it costs

Measured on 9 September 2026 against the real corpus: 26 meetings, 8 of them
with write-ups.

| | Size |
|---|---|
| Export with every notes body inlined | 92 KB |
| Export with notes omitted | 28 KB |
| All notes bodies together | 63 KB |
| Largest single `notes.md` | 12 KB |
| Transcripts on disk, deliberately **not** exported | 1.7 MB |

Extrapolating from a mean of about 8 KB per write-up, a year of daily
meetings is roughly 2 MB. Rewritten in full on every trigger.

The number is here because the machine has been at its disk limit for three
days and Hub established that it wrote 873 MB of that itself today. The
honest position is that this export is not a contributor and will not become
one, and that claim is worth pinning to a measurement rather than a shrug.

The transcript row is the one worth reading twice. Inlining transcripts would
multiply the export by roughly twenty at today's corpus and grow with audio
rather than with attention, which is a second reason for the
path-not-text rule beyond the accuracy argument.

## The meeting record

Field names follow Hub's existing `IndexMeeting` shape wherever one exists,
so its collector logic is adapted rather than rewritten.

```json
{
  "id": "2026-08-27-discovery-1",
  "revision": "b41f2c...",
  "date": "2026-08-27T08:37:16Z",
  "endedAt": "2026-08-27T08:46:10Z",
  "title": "Discovery 1",
  "lane": "business",  // or "personal", or "unknown"
  "participants": ["Kayleigh Adams", "Harry Ndlovu"],
  "summary": "Three TL;DR bullets, joined.",
  "topics": [],
  "decisions": ["..."],
  "actionItems": [
    {"text": "Send the revised pricing", "assignee": "Amir", "done": false,
     "due": "2026-09-01"}
  ],
  "notes": "# Discovery 1\n\n**Date:** ...full markdown body...",
  "notesPath": "C:\\...\\meetings\\2026-08-27-discovery-1\\notes.md",
  "transcriptPath": "C:\\...\\meetings\\2026-08-27-discovery-1\\transcript.md",
  "transcript": {
    "engine": "nemo-parakeet-tdt-0.6b-v3",
    "expectedAccuracy": "6.3%",
    "tracks": "system",
    "segments": 128,
    "lowConfidenceSegments": 3,
    "namesCorrected": 0,
    "speakerMethod": "separate audio tracks (attribution is exact)",
    "partial": false
  },
  "consent": {"obtained": true, "note": "recorded by the phone's own dialer"},
  "project": null
}
```

### The transcript is referenced, never inlined

`transcriptPath` points at the file. `transcript` carries its metadata. The
transcript **text** is not in this export and should not be added later.

This is a quality decision, not a privacy one. Amir has said Hub may see
everything, and Hub can open that path whenever it wants the raw record.

The reason is that the transcript is 92 to 97 percent accurate at the word
level, and Hub indexes `body` for full-text search and feeds it to its
prompts. Shipping the transcript text would put words nobody said into Hub's
search index, and let Hub's brain read mis-transcribed numbers and names as
fact. Real examples from this repo's own transcripts, before the corrector
was fixed: "CLI contact success Rael" for "CLI contact success rate",
"recalibrate your pricing to an Horn" for "to an hour".

`notes.md` is the artifact where those errors have already been repaired by
Claude reading them in context. It is the more accurate record, not the
lossier one. That is what the export carries.

**If a later change proposes inlining the transcript because more data is
better, this paragraph is the counter-argument.**

Hub endorsed this and generalised it, and the general form is the one that
should survive: **Hub never ingests raw ASR output, from any source.** That
belongs as a rule about Hub rather than a quirk of one collector, because the
next transcript to arrive will come from somewhere else, and a rule living
inside a single collector protects nothing but that collector.

### `lane` is derived, and must not be hardcoded

Hub's schema has `lane` as `business` or `personal`. Its `ops` collector
hardcodes `lane: "business"`, which is correct for the ops folder and wrong
here.

This repo holds both. One committed write-up is a mentoring conversation
about Amir's career, finances and family goals, and its own notes say it is
not client work and should not be quoted outside the repo. Filing that as
business would put personal financial detail into Hub's business surfaces.

**The field is three-valued: `business`, `personal` or `unknown`.**

Derivation, in order, and it never guesses:

1. An explicit `lane` in `meeting.json`, set by `mtg lane <meeting> <lane>`.
2. `personal` if the notes body carries the `**Personal, not client work.**`
   callout the meeting-notes skill produces.
3. `business` if the meeting has at least one named participant.
4. `unknown` otherwise.

Hub asked for a derivation that fails toward `personal`, on the correct
reasoning that an over-private meeting costs Amir a search miss while an
over-public one costs him a leak. Defaulting outright to `personal` was the
wrong way to honour that, because it would file most of the corpus as
personal and make the integration useless for the thing it is for.

`unknown` is the honest third answer, and it is affordable. Measured against
the real corpus on 9 September: **19 business, 1 personal, 6 unknown of 26.**
The six are impromptu Teams meetings and voice memos carrying no participants
at all. Refusing to guess costs a search miss on under a quarter of meetings,
and never files a private conversation as business.

Rule 3 is still a heuristic and can be wrong, but only in the direction of a
meeting that genuinely had named participants. Rule 1 is the correction, and
it is one command.

**Hub must handle `unknown` explicitly rather than coercing it.** Whatever it
does with the value, the one thing it must not do is treat it as `business`,
which would undo the point. Recording the lane during the write-up, so it is
stated rather than inferred by a regex, is the better long-term answer and is
out of scope here.

### `revision`, and why it exists

`revision` is a SHA-256 over exactly the fields Hub ingests, canonically
ordered: `title`, `lane`, `date`, `endedAt`, `participants` sorted,
`summary`, `decisions`, `actionItems`, `notes`.

It deliberately excludes `transcript`, `notesPath`, `transcriptPath` and
`revision` itself. A re-transcription that leaves the write-up unchanged must
not look like a change, or Hub churns its store over content it does not
hold. This is the rule Hub asked for, stated as an invariant: **the revision
covers what Hub stores, not what the exporter finds interesting.**

Because lists are sorted before hashing, a reordered export is not a change.

#### Why it exists, and what actually turned out to be true

The original reason was a defect in Hub: its collectors were first-write-wins
(`src/collectors/ops.ts:39` was `if (ctx.reader.messageExists("meeting",
m.id)) continue;`), so once a meeting id was in the store no later version of
it was ever read again. That matters more here than for the ops folder,
because the premise of this integration is that **every write-up is authored
headlessly by Claude, and write-ups get rewritten**: a re-run after a name
correction, a mid-call partial replaced by the real thing at Stop, an
improvement to the meeting-notes skill applied to old meetings. Hub would
keep whichever version arrived first, which is systematically the worst one,
with nothing reporting the mismatch.

**Hub has fixed this, in `c8113f9`.** The record of how the trade-off was
argued is kept here because two of the three claims were wrong, mine
included:

- I claimed Hub's write API could not update a message row, citing
  `src/store/write.ts:167`. **That was wrong.** `COLLECTOR_ALLOW` at :142
  grants `messages` read-write through an `rw([...])` helper, and
  `superseded_at` is absent from `IMMUTABLE_ON_UPDATE.messages`, so
  collectors could always supersede. My error came from grepping for the
  column name, which only matches `EXECUTOR_ALLOW` because that block names
  columns explicitly; a grant expressed as a helper over table names is
  invisible to a column-name search. The instrument could not see the branch.
- That error inverted the trade-off I put to Hub. I framed supersede as the
  expensive option needing a permission change. It needed none, and the
  cleaner shape was also the cheaper one.
- Neither of us had found the real constraint: **`UNIQUE (source,
  source_ref)`** on `messages` and `events`
  (`src/store/migrations/0001_initial.ts:113,142`). That is why a plain
  supersede-then-reinsert cannot work.

Hub's resolution, which this spec adopts: `source_ref` becomes
`<id>#<revision>` to sidestep the unique index, **and** superseded rows are
marked rather than left behind, because `#revision` alone would leave two
live versions of the same meeting in search and in every prompt. Messages,
events and actions move together.

#### The revision is advisory, not authoritative

Hub computes its own hash over the fields it actually stores and trusts that
one. It does not read this field to decide whether to re-ingest.

That is correct and this spec does not contest it. Hub's defect is live
against the `meetings-index.json` it already reads, so its fix cannot wait on
a field only this exporter emits; and a hash computed by the writer would
cover things the reader does not store.

`revision` is still emitted, and **a mismatch between the two is logged by
Hub as a signal rather than resolved in either direction.** A disagreement
about what "changed" means is exactly the thing worth making visible, and
neither side winning it silently is the point.

### Absence is not deletion

Stated as a requirement rather than left to be inherited from `ops.ts`.

A full-rebuild export that no longer contains a meeting is **not making a
claim that the meeting was deleted.** It may be a partial rebuild after an
interrupted run, a folder temporarily moved, or a meeting whose directory was
renamed. Hub must not remove or supersede a stored meeting because it stopped
appearing.

Meetings are effectively append-only in practice: `mtg prune` deletes audio
and leaves the meeting folder and its notes intact. If deletion is ever
wanted, it needs an explicit mechanism, such as the export declaring itself
authoritative over the whole set, and it should be designed then rather than
falling out of a missing record now.

### Deletion

A full rebuild means a meeting deleted on disk simply stops appearing. Hub's
hash cursor treats a changed file as work to do and its collector treats
absence as no-change, so a vanished meeting is not currently noticed.

That is acceptable for now and is stated so it is a decision rather than an
accident. Meetings are effectively append-only in practice; Amir deletes
audio via `mtg prune`, which leaves the meeting folder and its notes intact.
If Hub later wants deletion, the honest mechanism is that the export is
authoritative over the whole set and Hub clears rows whose ids are absent,
which needs the same write-permission change as superseding.

## When it is written

Every trigger performs the same full rebuild, so ordering and duplication do
not matter.

1. `mtg export-hub`, by hand.
2. After the headless write-up completes, in `server.py`'s `_write_notes`,
   the single point where a `notes.md` is finished. Best effort: a failure
   there is logged and swallowed, because Hub reading a stale export is a
   smaller problem than the widget failing after a call.
3. `mtg lane`, since changing a lane changes what Hub should file.

A meeting with no `notes.md` yet is still exported, with `summary`,
`decisions`, `actionItems` and `notes` empty. Hub learns that the meeting
happened, which is the fact with the shortest shelf life, and gains the
content when the write-up lands and `revision` changes.

`transcript.partial` is true when the transcript frontmatter says
`live: True`. Hub must not treat a partial as the record of the meeting.

## What the notetaker guarantees

- The file parses as JSON, or does not exist. Never half-written.
- Every `id` is unique within the file.
- `revision` changes if and only if `notes`, `decisions` or `actionItems`
  change.
- `notesPath` and `transcriptPath` are absolute, and either point at a file
  that exists or are null.
- No transcript text.
- `date` and `endedAt` are UTC ISO 8601, matching Hub's convention.

## What Hub needs to do

Stated as requirements, not implementation.

1. A `crm` collector, modelled on `ops.ts`, reading the path above. Absent
   file is not an error: the notetaker may never have run on this machine.
2. Re-ingest a meeting whose content changed, per `c8113f9`: `source_ref` of
   `<id>#<revision>`, with the superseded row marked rather than left live.
3. Treat a missing meeting as no claim, never as a deletion.
4. Derive `lane` from the record, not a constant, and handle the third
   value `unknown` without coercing it to `business`.
5. Do not ingest `transcript.partial: true` as a finished meeting.
6. Never ingest raw ASR output, from this or any other source.
7. Apply its own policy layer as `ops` does through `captureFor`. The
   notetaker does not know Hub's policy and must not pretend to. Hub deciding
   what it may store is correct and stays Hub's decision.

## Testing, and how this stops drifting

On the notetaker side the export is a pure function from the meetings
directory to a dict, so it tests with no audio libraries, no ffmpeg and no
speech model present, per this repo's import rule.

One test asserts the emitted record against the field shape in this document,
so a change here that would break Hub fails in this repo rather than silently
in that one. That test is the vendored half of the contract.

If Hub vendors this file, the pair should carry a hash and a self-test that
fails on drift, as the Hub and Mini CRM publish contract does. Changed by
agreement, never unilaterally.

## Open questions for Hub

Settled: the revision shape, in `c8113f9`. Still open:

1. Do you want `notes` as the message `body` verbatim, or `summary` as the
   body with `notes` kept separately? Verbatim gives better search and a
   heavier row.
2. Should action items become rows in your `actions` table as `ops` does?
   They carry an assignee that is frequently `@me`, which is Amir, and your
   `personByNormalisedName` lookup will need to resolve that.
3. Is `%LOCALAPPDATA%\mtg\exports\meetings.json` reachable from Hub's
   sandbox, or do you need it under your own data directory?

## Not in scope

- The transcription accuracy feedback signal (`corrections.json`). Separate
  work, needs Amir's go-ahead, parked.
- Any UI. Mini CRM owns the shared design system and Hub is its first
  implementation.
- The notetaker reading Hub's `organisations.json`. Deferred, and not
  because it is unwanted. Two findings on 9 September: the file does not
  exist on this machine, because Hub's data directory (`HUB_DATA_DIR =
  app.getPath("userData")`, so `%APPDATA%\Hub`) holds only an Electron
  profile and no `exports` directory or `store.db`; and consuming it safely
  is not the small change it looked like, because `transcribe.correct_names`
  splits every vocabulary term into single words, which is the mechanism
  behind the 106 false substitutions of 6 September. An uncurated
  organisation list would reintroduce that, guarded only by a hand-written
  list of ten ordinary words. Doing it properly means the vocabulary carries
  which terms may be split, which changes the corrector. Its own design, its
  own tests.
