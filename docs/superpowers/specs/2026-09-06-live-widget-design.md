# Live meeting widget

**Status:** approved in conversation on 6 September 2026; built that day. A
review of this spec found 47 issues before the build; the ones that held
changed the design below, and this document was brought into line with the
code afterwards. Where the two ever disagree, the code and its tests are the
record.

## What it is

A Grammarly-style widget: a small always-on-top window that lives at the edge
of the screen from login, shows the next meeting, records when told to, and
while a call is running shows what has been agreed so far, questions worth
asking, and what is already known about the person. After the call it floats
with the finished notes. It has an ask box, answered by Claude, that remembers
the conversation for that meeting.

Everything intelligent still comes out of the user's Claude Code subscription.
The widget never holds an API key and never imports `anthropic`. It runs
Claude Code headlessly (`claude -p`) in the repo folder, with the same skills
and commands a person would type, and shows the result.

## Decisions taken in conversation

| Question | Answer |
|---|---|
| What to show live | Next steps and questions to ask (A); CRM context on the person (C). No transcript ticker. |
| How live panels refresh | Automatically after about two minutes of new speech, plus a refresh button. |
| Screen sharing | The window is excluded from screen capture, always. |
| At Stop | Transcription finishes, then `/notes` runs headlessly at once; the widget floats with the notes. |
| Ask box | One running Claude conversation per meeting, so follow-ups work. |
| Between calls | One process from login: a pill showing the next meeting and Start; expands when recording; replaces the separate watcher. |
| Window technology | pywebview (WebView2) hosting the existing local page; Python owns the window. |
| Headless Claude | Approved. Uses the subscription's models. Requires a one-time `claude` + `/login` by the user; the widget detects the missing login and says so. |

## Constraints that do not move

- No API key, no `anthropic` import, no paid service. Headless Claude Code is
  the subscription, not an API.
- The consent switch stays, in the UI and server-side. The widget only ever
  offers to record; nothing starts without the switch and the button.
- Two tracks, Parakeet, names corrected after transcription, no denoising.
- `transcript.md` and `transcript.json` are machine-authored; the live
  transcriber is the machine. Claude writes `notes.md` and contact files, as now.
- `store.py` owns the file layout. Nothing here writes into `meetings/` by hand.
- Wear headphones. The widget says so where the app did.

## Architecture

```
                    ┌──────────────── widget process (pythonw, from login) ────────────────┐
                    │  widget.py      pywebview window (frameless, on top, capture-hidden) │
                    │      │  loads http://127.0.0.1:<port>/  and exposes window controls   │
                    │  server.py      Session + JSON API (as now) + live/brief/ask/notes    │
                    │      ├─ live.py        chunked Parakeet over the growing WAVs        │
                    │      ├─ assistant.py   claude -p bridge: prep, brief, ask, notes     │
                    │      └─ calendar poll  (watcher.due_now) → expand + prefill          │
                    └───────────────────────────┬──────────────────────────────────────────┘
                                                │ spawns, as now
                                       recorder process (cli _record → capture.py)
                                       writes mic.wav / system.wav continuously
```

The recorder is unchanged. The widget process is the old server process plus
three things: a window it owns, a live transcriber, and a Claude bridge.

## Components

### `notetaker/live.py` — live transcription

`LiveTranscriber(meeting_dir, vocabulary, transcribe_fn=None)` does the work;
`LiveProcess` runs one in a worker process (`python -m notetaker.live`) and
speaks to it in one-line JSON, because loading the model holds the
interpreter lock for seconds at a time (11.7 s on the laptop, in stretches of
up to 7 s) and would freeze the widget's API. The widget process never loads
a model. The fallback, transcribing the finished files whole, runs in a worker
too.

- `tick()` every `INTERVAL = 30` s: for each track, read the PCM appended
  since the last pass straight from the growing WAV (length from the file
  size, since the header is only right at Stop; the recorder flushes twice a
  second), transcribe `[committed − OVERLAP, end]` with `OVERLAP = 3` s on a
  numpy array through the same Parakeet, VAD and timestamp chain, and shift
  segment times to the meeting timeline. A pass takes at most
  `MAX_PASS_SECONDS = 120` s of audio; a widget adopting a long recording
  catches up over successive ticks without waiting between them.
- Deduplication is a split rule, not a drop rule. A segment that ends before
  `committed` is a repeat and is dropped. One that starts more than
  `JOIN_TOLERANCE = 0.5` s before `committed` and ends after it is VAD joining
  speech across the line; it is split at `committed` on the model's per-token
  timestamps, keeping the tail. A segment starting closer than that is the
  held-back segment heard again and is kept whole. With no token timestamps
  the whole segment is kept from `committed`: repeated words cost less than
  lost ones.
- The last segment of a pass is held back if it ends within `TAIL = 1` s of
  the end of the audio; `committed` moves to its start. When nothing is held
  back, `committed` never advances into the last `TAIL_SILENCE = 2` s.
  Verified on the laptop: VAD emits a segment cut by the window end ("Monty
  smide from"), which the hold-back then hears whole.
- `new_speech_seconds()` is the summed duration of segments kept since the
  last reset, across both tracks; the Session briefs when it reaches 120.
- Files are written through `transcribe.write_transcript` (atomic), the same
  function `transcribe_meeting` uses, with `live: True` in the meta until
  `finish()`; `transcribe_meeting` writes `live: False`. The meeting-notes
  skill knows what `live: True` means.
- `resume()` restores segments from a live `transcript.json` and moves each
  track's line to its last segment's end, so a reopened widget carries on.
- Any failure in a pass or a write lands in `error`; `finish()` then raises
  `LiveError` and the Session transcribes the files whole in a fresh worker.
- Cost, measured: 3–4 s of CPU per 10 s of speech at four inference threads,
  nothing in silence; roughly a third of a core while someone talks.

### `notetaker/assistant.py` — the headless Claude bridge

- `available()`: the path of `claude.cmd` (npm's launcher) or `claude`.
- `run(prompt, *, schema, resume, session_id, allowed_tools, timeout, wait)`:
  `claude -p --output-format json --restricted [--json-schema …]
  [--resume id | --session-id id] --allowedTools … --disallowedTools Bash
  Write(meetings/**/transcript.*) Edit(meetings/**/transcript.*)`, with the
  prompt on stdin (never on a Windows command line), `cwd = repo_root()`, no
  console window, and an environment with every `ANTHROPIC*` variable removed
  and every `CLAUDE*` one removed except `CLAUDE_CODE_OAUTH_TOKEN` and
  `CLAUDE_CONFIG_DIR`, which carry a headless login. Read-only calls get
  `Read, Glob, Grep, Skill`; `/notes` adds `Write` and `Edit` scoped to
  `meetings/**/notes.md` and `meetings/**/meeting.json` (not contact files:
  they hold the user's own notes and a transcript can say anything), and a
  15-minute timeout. The CLI's cost estimate is logged, not acted on; an API
  key inside Claude Code's own settings is not something the widget can see.
- `Result(ok, text, data, session_id, error, detail, cost_usd)`; `error` is
  `login` (with the one-line instruction), `missing`, `busy`, `timeout` or
  `failed`. One process at a time; a brief that finds the lock busy returns
  `busy` and the next tick tries again.
- Prompts are the command files in `.claude/commands/`, read here with
  `$ARGUMENTS` filled in: `/prep` at Start for the first participant with a
  contact file; `/live-brief` with `BRIEF_SCHEMA` and the previous brief
  inline; `/ask` on the first turn under a session id derived from the
  meeting id (`uuid5`), retried with `--resume` if the CLI already holds
  that conversation, then plain prompts with `--resume`; `/notes` at Stop
  with a headless note appended.
- **Not yet exercised against a logged-in CLI.** On this machine `claude -p`
  answers "Not logged in"; the CLI keeps its own login. The stand-in in the
  tests replies with the CLI's documented JSON. The first real run after the
  user's `/login` is the acceptance test for this component.

### `notetaker/server.py` — Session additions

State in `GET /api/state`: `live {segments, seconds, error}`, `brief` (with
`as_of` and `speech_seconds`), `brief_state`, `brief_error`, `about`,
`about_person`, `about_state`, `chat`, `notes`, `notes_state`
(`idle|running|done|error|login`), `notes_error`, `claude {available,
login_needed, turns}`, `capture_hidden`, `window`, and `poll_ms` (700 while
anything is happening, 2500 otherwise). The calendar, recent-meetings and
which-claude parts of a poll are cached for three seconds. Meeting ids from
the client must match the shape the tool makes.

Flow:

1. `start()` as before, waiting up to 15 s for the recorder and killing one
   that misses; then the live worker opens on its own thread and `/prep`
   runs for the first participant the CRM knows.
2. The live thread ticks every `INTERVAL`, ticks again at once while the
   worker is behind, backs off if a pass was slow, and hands a `/live-brief`
   to a worker thread when two minutes of new speech have accumulated.
   Briefs, by hand or otherwise, never run more often than 30 s, never once
   Stop has begun, and after failures automatic ones back off 2, 4, 8
   minutes and then stop until the next meeting. No worker call is ever
   made while the Session lock is held.
3. `stop()`: `capture.stop_recording` first and to completion; then
   `finish()` in the worker (or the files whole, in a fresh worker, on
   `LiveError`); then `finalize_meeting`, `link_contact`, `rebuild_index`;
   then state `writing` while `/notes` runs; then `done`. A `login` error
   leaves the transcript and shows the instruction; the visible "Write up in
   Claude Code" path remains. Every headless turn is counted and shown; a
   success clears the login banner.
4. `POST /api/ask` answers on a thread and keeps the conversation id even
   from a failed turn; `POST /api/show` floats an earlier meeting's notes;
   `POST /api/window` forwards `collapse|expand|toggle|quit` to the window,
   refusing `quit` while a meeting is in progress.
5. `_calendar_loop` uses the watcher's `due_now` and seen-file, so an offer
   is made once per meeting; it expands the window and the suggestion
   prefills as before.
6. A reopened widget adopts a running recording, resumes its live transcript
   and its About panel, reloads the ask conversation's id, and notes a
   recording older than four hours.

The watchdog that closed the old server when the Edge window went away is
only installed by `serve()` with its defaults; the widget's process lives as
long as its window, and the widget's Edge fallback runs `serve()` with the
watchdog off and the calendar loop on.

### `notetaker/widget.py` — the window

- `main()`: if `app.lock` answers, bring the running window forward and exit;
  otherwise make the process DPI-aware, `server.make_server()`, the calendar
  loop, and a pywebview window: frameless, on top, 380 wide, 64 high as a
  pill, up to 700 expanded but never taller than the screen allows, at the
  last saved position clamped on screen, or bottom right of the work area.
  All geometry is in logical pixels, which pywebview takes and scales by the
  display DPI (150% on the laptop).
- It opens as the pill. It expands when a calendar meeting is due, when a
  recording starts, and when notes land; it collapses on "New recording",
  and by the chevron or a double-click on the strip at any time.
- Once the window is visible and sized, the HWND from pywebview's own form
  gets `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, verified by
  reading it back, plus the tool-window style and topmost through one
  `SetWindowPos` with the frame-changed flag (hiding and re-showing the
  window from that thread wedged WebView2). Only this process's windows are
  ever considered; an Edge window with the same title is not touched.
  `session.capture_hidden` records whether it took, and the page shows a
  banner whenever meeting content is on screen if it did not.
- JS API `collapse/expand/toggle/quit/shape`; `quit` is refused while a
  meeting is in progress. The pill is a drag region and carries a Stop
  button while recording.
- If pywebview or WebView2 is missing, or the window fails, `main()` logs it
  and runs the Edge window with the calendar loop and no watchdog:
  everything but the always-on-top and capture exclusion, and the page hides
  the host-only controls.

### `notetaker/ui/index.html` — the page, redesigned as the widget

One page, two shapes. Pill: drag handle, status dot, one line ("Next: Catchup
14:30 · Monty Smythe" / "Recording 12:04" / "Notes ready"), expand chevron.
Expanded, in order:

1. Header: title, elapsed, collapse, setup link.
2. Consent block and Start, exactly as today, shown when idle.
3. **Next steps** (owner, text, timestamp) and **Ask them** (questions), from
   `brief`; a refresh button; "as of 00:14:20" line; while recording and
   after.
4. **About <person>**, the `/prep` markdown, collapsible.
5. **Ask** box with the conversation beneath it.
6. **Notes**, after Stop: `notes.md` rendered; "Open folder"; "Record another".
7. Login hint banner when `claude.login_needed`.

Markdown is rendered client-side with a small dependency-free converter
(headings, lists, bold, quotes, links); no external scripts.

### Setup, CLI, docs

- `setup-windows.ps1`: installs `pywebview`; verifies the WebView2 runtime
  (registry key `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\
  {F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`); checks `claude` is on PATH and
  prints the one-time login step; Desktop and Startup shortcuts point at
  `notetaker.widget`.
- `mtg doctor`: three new lines: pywebview importable, WebView2 present,
  Claude Code found (and, if the last recording.json shows a login error,
  says so).
- `mtg app`: the widget; `--browser` the Edge window; `--classic` Tkinter.
- README, HANDOFF, docs/setup-windows.md, CLAUDE.md commands section.

## Failure handling

| Failure | Behaviour |
|---|---|
| Live worker fails to open, or a pass or write raises | `live.error` set; the panel says so; recording continues; Stop transcribes the files whole in a fresh worker. |
| A WAV write fails | The packet is skipped and counted; the track goes on; `recording.json` says how many. |
| Claude not installed | Panels say so; notes via the visible button as before. |
| Claude not logged in | Banner with the one instruction; retried on the next brief; cleared by the next success. |
| Claude call times out or errors | Last good brief kept with an error line; automatic briefs back off, then stop for this meeting. |
| Two Claude calls wanted at once | Lock; briefs skip, asks and notes wait. |
| Window cannot be created | Edge window with the calendar loop; log says why. |
| Widget closed during a recording | Recording continues; reopening adopts it and resumes the live transcript from the files. |
| Quit asked for during a recording | Refused, with "Stop the recording first." |
| Recorder does not report in within 15 s | It is killed; the state says so. |
| Second launch | The running window is brought forward; no second server. |

## Testing

- `tests/test_live.py`: a WAV grown in steps with a decoding fake; absolute
  times, no repeats across the overlap, the held-back tail, the split of a
  joined segment on token timestamps, silence advancing the line, the two
  tracks interleaving, capped passes and catching up, the error contract,
  the file format against `transcribe_meeting`, and the worker process end
  to end (open, tick, finish, a dead worker, resume, the fallback, the
  protocol in-process).
- `tests/test_assistant.py`: a stand-in `claude` on PATH; flags, stdin
  prompt, environment, tools, schema, session ids and the resume retry, the
  login and other error shapes, timeout, the lock.
- `tests/test_server_live.py`: the Session over real HTTP with fakes for the
  worker and Claude: start → prep → briefs → ask → stop → notes, the
  fallback, the login path, throttles, turns, earlier meetings, window
  hooks, quit refusal.
- `tests/test_widget.py`: geometry in logical pixels, the pill default, the
  clamp, capture exclusion against a fake user32, settings, the JS API.
- Hardware: the widget launched as the shortcut does, its window, capture
  exclusion, collapse and expand, the consent gate, a solo call with speech
  through the speakers, live segments, Stop, and every Claude path invoking
  the real CLI and surfacing the missing login. Done four times on 6
  September; the last runs were disturbed by other sessions' workloads on
  the same laptop, which is worth knowing when reading the log.

## Out of scope

Live transcript ticker; multiple simultaneous meetings; anything that sends
data anywhere but the user's own Claude Code.
