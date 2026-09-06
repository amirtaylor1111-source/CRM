# Handoff

You are continuing work that was built entirely in a cloud container which
could never reach Amir's laptop. This file is the transfer. Read CLAUDE.md
too — it holds the rules; this holds the state and the reasoning.

---

## What this is

A meeting recorder that runs on Amir's own machine, transcribes offline, and
hands the transcript to Claude Code for the write-up. It exists because
Fathom costs money and stamps a free-tier badge on his client calls, and
because he wants the intelligence to come out of his existing Claude
subscription rather than a second bill.

**The constraint that shapes everything: no paid API.** Nothing here may
import `anthropic`, read an API key, or call a cloud service. Local code
captures, transcribes and stores; Claude does the thinking by reading files
in an ordinary session. If you are ever tempted to automate the write-up
with an API call, don't — that is the one thing the design rules out.

## The machine

Dell Latitude 3440, Windows 11 Pro. Intel i5-1345U — 10 cores but 8 are
efficiency cores, so treat it as 4–6 useful ones. 16 GB RAM, Intel UHD
graphics, **no CUDA**. 237 GB disk with ~43 GB free when this was written
and 30 GB after the 6 September 2026 install (the venv and model account
for about 2.5 GB of that; the rest is unexplained), which is why audio is
captured at 16 kHz mono and `mtg prune` exists.

Python was the Microsoft Store placeholder. The setup script now installs
real Python via winget on its own.

## Decisions already made, and why

**Two audio tracks, not one.** The mic and the system loopback are recorded
to separate files. Speaker attribution then comes from which file the audio
was in, rather than from a diarisation model that gets it wrong roughly one
time in eight on real meeting audio. This is the single most valuable
decision in the project. It only holds if Amir wears headphones — on
speakers the far end bleeds into the mic and both tracks contain both
parties. Say so in the docs and in `doctor`; don't quietly drop it.

**Parakeet, not Whisper.** `nemo-parakeet-tdt-0.6b-v3` via onnx-asr at int8.
It beats Whisper large-v3 on meeting audio (~6.3% vs ~7.4% word error) while
running roughly ten times faster on CPU — about six minutes for a one-hour
meeting on this laptop. It is also a transducer, so it structurally cannot
hallucinate fluent sentences into silence the way Whisper does. For a record
of what people committed to, an invented sentence is far worse than a missed
word. faster-whisper stays wired in as a fallback with its documented
anti-hallucination parameters set.

I originally recommended `large-v3-turbo` and was wrong: turbo is a speed
optimisation and scores the same as large-v3 on meeting audio. Don't
re-introduce it.

**Names corrected after transcription, not hinted before.** Whisper's
`initial_prompt` only survives the first 30 seconds of a file and can leak
into output. Instead, `store.vocabulary()` returns every contact and company
in the CRM and a fuzzy pass repairs mis-transcriptions against it. The
threshold is 0.74, calibrated against real cases: it fixes "Akme"→"Acme" and
"Kagisso Mzizzi"→"Kagiso Mzizi", and leaves ordinary words alone. A large
stoplist of common English words does most of the protective work. Every
substitution is logged in `transcript.json` so it can be audited or undone.

**No noise reduction.** It sounds like it should help. A 2025 study found
denoising degraded transcription accuracy in all forty configurations
tested, by up to 46 percentage points. The rawest capture is the most
accurate one.

**Connectors live in the Claude session, never in the Python.** Fathom and
Outlook are reached by Claude using MCP tools; the Python side only ever
reads a JSON file Claude wrote. This keeps the no-API rule intact and makes
every import path testable with no network.

**Consent is a data field, not a lecture.** `meeting.json` records
`consent_obtained` and a note. The UI's start button stays disabled until
the switch is flipped, and that gate is enforced server-side too, not just
by a greyed-out button. Amir asked for covert recording at the very start
and that was declined; he then said he would ask everyone, and the tool is
built around making that easy. Don't add nagging, and don't remove the gate.

## What is in the repo already

19 meetings imported out of Fathom (July–September), 18 contacts, and the
next four calendar events synced from Outlook. Two data errors were found
and fixed by cross-referencing the calendar against Fathom's invitee list:
**"John Smith" was actually Monty Smythe** (`montysmythe@outlook.com`,
wrong across four meetings and already poisoning the name-correction
vocabulary), and Ronan O'Higgins was filed under Aged Ventures, which is
Amir's own company — he is at Open (`open.cx`).

Do not re-import or re-record any of this.

## Verified vs not

**Verified by execution here:** the CRM store, contact splicing that
preserves hand-written notes, idempotent linking, atomic writes, slug
collisions, the Fathom and phone importers, the calendar layer, the name
corrector's false-positive boundary, the whole transcription pipeline on
real espeak-generated speech, the local HTTP API over real sockets, and the
recording lifecycle driven by a fake audio device. 251 tests.

**Found by installing the libraries in the container, before any hardware
run** (the hardware run itself is described below): the `soundcard` WASAPI
calls and the onnx-asr chain. Installing those libraries
here caught two real bugs — `pip install onnx-asr` does not pull in
onnxruntime (it needs `[cpu,hub]`), and `recognize()` takes no `timestamps`
argument; the real chain is
`load_model(quantization="int8").with_vad(load_vad("silero")).with_timestamps()`.

**Verified on the laptop itself, 5 September 2026:** setup runs end to end
(it had to install Python via winget), `mtg doctor` passes every check, both
tracks record through WASAPI, the loopback track transcribes correctly with
the CRM's names intact, the app opens in Edge and the consent gate holds in
the window and on the server. Four things had to be fixed on the way: the
setup script contained an em dash, which Windows PowerShell 5.1 reads as a
smart quote in a BOM-less file and refuses to parse; onnx-asr 0.12 hands the
VAD pipeline's results back as a generator, which `transcribe.py` was
wrapping in a list and reading as nothing; the microphone array opens its
stream one to two seconds after the loopback does, so `capture.py` now pads
each track with silence back to a shared start instant; and the microphone
stream pauses for a moment every ten seconds or so at idle and constantly
under CPU load, which soundcard's Windows backend fills with invented
silence before the real frames arrive too, so the mic file ran 1% long at
idle and 26% long under six CPU burners (a minute or more of drift across
an hour). On Windows, `capture.py` therefore no longer uses soundcard's
record() loop at all: it reads the WASAPI packets directly and places each
one in the file at the QueryPerformanceCounter time WASAPI stamps it with,
so the only synthetic content is silence standing in for time in which the
device produced nothing, nothing is ever deleted, and no sample value is
ever changed. `recording.json` records the lead, the filled silence, the
discontinuity count and any overlap per track. The block loop remains as
the fallback for the fake device in the tests and for other platforms.

The microphone track was verified by Amir himself: he pressed Start in the
window, spoke for fifteen seconds, and the transcript came back labelled
"Me" with what he said. One observation for anyone testing without him: on
this particular laptop, speech played through its own speakers reached the
mic track only as a faint residue (the Intel array attenuates its own
playback; peak 0.19 against 0.93 on the loopback) and nothing of it
transcribed, so text-to-speech through the speakers is no test of the mic.
Do not generalise from that. The headphones rule above still stands: louder
playback, a longer call, or any other machine, and the far end lands on the
mic track labelled "Me".

## The one test that matters

```powershell
.\mtg.cmd start --solo --title "Install test"
# say something out loud, wait ten seconds
.\mtg.cmd stop
```

Then check `meetings\<newest>\`: `mic.wav` and `system.wav` should both exist
and be non-empty, and `transcript.md` should roughly contain what was said.
Everything else has tests. This path has none.

Then open the app — Desktop shortcut, or `.\Notetaker.cmd` — and confirm the
widget appears as a pill at the bottom right, expands when you click the
chevron, and keeps the Start button grey until the consent switch is flipped.

## The widget (added 6 September 2026)

Amir scrapped the no-features rule that evening and asked for a
Grammarly-style widget: always on top, live during the call, floating after
it. The design conversation and its decisions are in
`docs/superpowers/specs/2026-09-06-live-widget-design.md`. The short form:

- `notetaker/widget.py` owns a frameless always-on-top window (pywebview on
  WebView2) that shows the same local page as before, collapses to a pill at
  the bottom right, runs from login, and is excluded from screen capture
  with `SetWindowDisplayAffinity`, so "questions to ask them" never appear
  in a share. Two things watching the calendar would offer twice, so the
  Startup shortcut now launches the widget and setup removes the old
  watcher shortcut; `mtg watch` still exists.
- `notetaker/live.py` transcribes the growing WAVs every 30 s through the
  same Parakeet chain, splitting any segment VAD joins across its committed
  line with the model's token timestamps, and keeps `transcript.md` and
  `.json` current with `live: True` in the frontmatter. Measured on the
  laptop: 3–4 s of CPU per 10 s of speech at four threads, so a call costs
  roughly a third of a core while someone is talking, nothing in silence.
- `notetaker/assistant.py` runs Claude Code headlessly, `claude -p` in the
  repo with the prompt on stdin, `--restricted`, read-only tools plus
  `Skill`, and for `/notes` the right to write `notes.md` and the participant
  list, not contact files: those hold Amir's own notes, and a transcript can
  carry anything a caller said, so contact updates stay with an interactive
  `/notes`. The environment it gets has every `ANTHROPIC*` variable removed
  and every `CLAUDE*` one except the two that carry a headless login. It is
  the subscription, not an API; nothing here holds a key. What it cannot see
  is an API key configured inside Claude Code's own settings; if one is
  there, the CLI would bill it, and only the user can check that.
- The Session in `server.py` starts `/prep` on the first known participant
  at Start, a `/live-brief` after every two minutes of new speech (never
  more often than 30 s, backing off after failures), keeps one `/ask`
  conversation per meeting, and runs `/notes` the moment Stop's transcript
  is done. The consent gate is unchanged, in the page and on the server.

After pulling or upgrading, re-run `setup-windows.ps1`. It is the script that
writes the Desktop and Startup shortcuts, and an older install leaves them
pointing at the entry points that came before the widget.

**Verified on the laptop:** the window, the capture exclusion, the pill,
live transcription during a solo call with speech through the speakers,
Stop finishing the live transcript in seconds, and every headless
path against a stand-in `claude` (251 tests). Two more things surfaced on
the laptop and were fixed: loading the model holds the interpreter lock for
about twelve seconds, so live transcription runs in a worker process per
call and the widget process never loads a model; and the wave module's
header patch on every write failed once with EINVAL under load and killed
a track, so the recorder now appends raw frames, flushes twice a second,
patches the header at close, and skips a packet rather than dying. **Not yet verified:** a real
headless Claude Code call. The `claude` CLI on this machine had never been
logged in, and that is Amir's to do: open a terminal, run `claude`, then
`/login`. Until then the widget records and transcribes, and every panel
that needs Claude shows that one instruction instead.

## How the pieces fit

```
the widget / mtg start  →  two WAVs  →  live.py every 30 s  →  transcript.md (live)
                                              ↓ during the call            ↓ at Stop
                              /prep, /live-brief, /ask headlessly    /notes headlessly
                                              ↓                            ↓
                                    the widget's panels          notes.md + contacts/*.md
```

`store.py` owns all file layout — slug collisions, idempotency, the managed
block in contact files. Never write into `meetings/` or `contacts/` by hand;
go through it. The region of a contact file between `## Meetings` and
`<!-- /meetings -->` is the tool's; everything else in that file is the
human's and must survive every edit.

## Coverage, and the hard limit

| Call type | How |
|---|---|
| Teams, Zoom, Meet | laptop recorder |
| WhatsApp | laptop, via WhatsApp Desktop |
| Cellular | phone records it, `mtg phone <folder>` imports |
| WhatsApp on the handset | **impossible** |

WhatsApp calls cannot be recorded by any app on any phone. Android excludes
`VOICE_COMMUNICATION` audio from the playback-capture API deliberately, iOS
has no loopback API at all, and the calls are end-to-end encrypted anyway.
Don't go looking for a workaround; there isn't one short of rooting the
phone. The answer is WhatsApp Desktop on the laptop, where loopback capture
treats it like any other app.

## Open questions for Amir, not for you to decide

- His client transcripts and notes are committed to GitHub. Private repo,
  but it is his commercial history with a third party. He was offered a
  gitignore that keeps only the structure versioned and has not answered.
- Screen recording exists behind `--video` but needs ffmpeg and has never
  run. It is probably not worth it: notes come from what was said, and video
  costs about a gigabyte an hour against 43 GB free.

## Working on it

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q     # 251 tests, all must stay green
```

Modules must import on a machine with no audio libraries, no ffmpeg and no
speech model, because `mtg doctor` has to run on exactly that machine to
say what is missing. Keep optional imports lazy and guarded, and make the
doctor degrade to a FAIL line rather than a traceback — it has already been
bitten by that once, when a `soundcard` import raised something that was not
an ImportError.

Never weaken or delete a test to make something pass.
