# Setup on Windows

About ten minutes, most of it downloads. You do not need admin rights.

## 1. Install Python

If you do not already have it, get Python from
[python.org/downloads](https://www.python.org/downloads/).

**On the first screen of the installer, tick "Add python.exe to PATH".**
This is the step people miss, and everything else fails without it.

To check it worked, open PowerShell and run:

```powershell
python --version
```

You want 3.11 or newer.

## 2. Run the setup script

Open PowerShell in this folder (Shift + right-click the folder in Explorer →
"Open PowerShell window here") and run:

```powershell
powershell -ExecutionPolicy Bypass -File setup-windows.ps1
```

The `-ExecutionPolicy Bypass` part is needed because Windows blocks unsigned
scripts by default. It applies to this one command only and changes nothing
permanently.

The script creates a `.venv` folder here, installs three packages into it,
downloads the speech model (about 670 MB, once), and then runs a check.

## 3. Read the check

The last thing the script prints is the output of `mtg doctor`:

```
  Machine   Windows 11, 10 cores / 12 threads, 16 GB RAM, CPU only, 43 GB free
  Engine    nemo-parakeet-tdt-0.6b-v3  (6.3% expected word error)
  Speed     1-hour meeting -> about 6 minutes

  PASS  audio library
  PASS  numpy
  PASS  microphone (1 found)
  PASS  system audio (1 found)
  PASS  transcription engine (parakeet)
  PASS  disk space (43 GB free)
```

Every line should say PASS. If one does not, it prints the command that fixes
it.

## 4. Wear headphones

Not optional, and not about sound quality. The tool records you and the call
as two separate tracks, which is what makes it able to tell who said what. On
speakers, the far end comes back through your microphone and lands on both
tracks, and that advantage is gone.

## Your first recording

```powershell
.\mtg.cmd start --with "Jane Doe" --title "Acme renewal"
```

It shows you a sentence to say out loud and asks you to confirm you have said
it. Then it records in the background, so you can close that window.

When the call ends:

```powershell
.\mtg.cmd stop
```

It stops, transcribes, and tells you to run `/notes` in Claude Code.

## Troubleshooting

**"running scripts is disabled on this system"** — you left off
`-ExecutionPolicy Bypass`. Use the full command in step 2.

**"system audio (0 found)"** — Windows has no active output device. Play
something, check Settings → System → Sound, then run `mtg doctor` again.

**"microphone (0 found)"** — check Settings → Privacy & security → Microphone
and confirm desktop apps are allowed to use it.

**Transcription is slower than you want** — pick a smaller model:

```powershell
$env:MTG_ENGINE = "small"
```

Accuracy drops from about 6% word error to about 14%, which is noticeable on
names but rarely changes the meaning of the notes.

**Running low on disk** — `mtg prune` deletes the raw audio from meetings
that are already transcribed. Use `--dry-run` first to see what would go.
