# Picking this up on the Windows laptop

You are a Claude Code session running **on Amir's Windows 11 machine** (Dell
Latitude 3440, i5-1345U, 16 GB RAM, no GPU, ~43 GB free). Everything in this
repo was built by a session running in a cloud container, which could never
reach this machine. That is the only reason this file exists.

Your job is narrow and finite. Do not continue building features.

## What this is

A local meeting recorder. It captures the mic and the system audio as two
separate tracks, transcribes them offline with Parakeet, stores meetings and
contacts as plain markdown, and hands the transcript to Claude Code for the
write-up. No paid API anywhere — read CLAUDE.md before touching anything.

## Your job

1. **Install it.**

   ```powershell
   powershell -ExecutionPolicy Bypass -File setup-windows.ps1
   ```

   It creates a venv, installs `soundcard`, `numpy` and
   `onnx-asr[cpu,hub]`, downloads the Parakeet model (~670 MB), installs the
   package with `pip install -e .`, puts a shortcut on the Desktop and a
   watcher in Startup, then runs the setup check.

2. **Run the setup check and read it properly.**

   ```powershell
   .\.venv\Scripts\python.exe -m notetaker.cli doctor
   ```

   Every line should say PASS. The two that have never been tested on real
   Windows hardware are **microphone** and **system audio** — those use
   WASAPI loopback via the `soundcard` package, written against its source
   but never executed against a real device.

3. **Record a real ten-second test.**

   ```powershell
   .\mtg.cmd start --solo --title "Install test"
   # say something out loud, wait ten seconds
   .\mtg.cmd stop
   ```

   Then check `meetings\<newest>\`: `mic.wav` and `system.wav` should both
   exist and be non-empty, and `transcript.md` should contain roughly what
   you said. This is the actual acceptance test for the whole project.

4. **Open the app** by double-clicking `Meeting Notetaker` on the Desktop,
   or `.\Notetaker.cmd`. It should open a dark window in Edge. Confirm the
   Start button stays greyed out until the consent switch is flipped.

5. **Fix what breaks**, but only Windows-specific breakage: device
   enumeration, WASAPI behaviour, path handling, the PowerShell script, the
   Edge app-mode launch. Run `python -m pytest tests/ -q` before and after —
   133 tests should pass, and they must still pass when you are done.

6. **Push** to `claude/meeting-notes-screen-record-mu2b26` and say what you
   changed.

## What NOT to do

- **Do not add features.** Not screen recording, not a tray icon, not a
  prettier UI. If something looks missing it was almost certainly a
  deliberate decision; the commit messages say why.
- **Do not touch** `store.py`, `schema.py`, `transcribe.py` or the
  `.claude/` skills unless a Windows bug is genuinely in them. They are
  covered by tests and were verified against the real libraries.
- **Do not weaken or delete a test** to make something pass.
- **Do not add an API key or any paid service.** The entire design rests on
  summarisation happening inside a Claude Code session on Amir's existing
  subscription. See CLAUDE.md.
- **Do not re-record or re-import** the 19 Fathom meetings or the calendar.
  They are already in the repo.

## Things already known to be true

- Python on this machine may be the Microsoft Store stub, which is not real
  Python. The setup script detects and rejects it and tells you to run
  `winget install Python.Python.3.12`. If you install Python, open a **new**
  terminal afterwards or PATH will not have updated.
- `ffmpeg` is absent and is only needed for `mtg phone` (importing Samsung
  call recordings) and for optional screen capture. Audio meetings do not
  need it.
- The engine choice is automatic: this machine gets
  `nemo-parakeet-tdt-0.6b-v3` at int8, roughly six minutes to transcribe a
  one-hour meeting.
- Logs are at `%LOCALAPPDATA%\mtg\mtg.log`. Read them when something fails.

## Report back with

The full output of `mtg doctor`, whether the ten-second test produced a
correct transcript, and anything you changed. That is what the cloud session
is waiting for.
