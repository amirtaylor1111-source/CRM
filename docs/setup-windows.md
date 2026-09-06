# Setup on Windows

About ten minutes, most of it downloads. You do not need admin rights.

## 1. Install Python

Open PowerShell and check what you have:

```powershell
python --version
```

**If that opens the Microsoft Store, you do not have Python.** Windows ships
a placeholder of that name which does nothing except advertise the Store. The
setup script detects and skips it, but you still need a real install:

```powershell
winget install Python.Python.3.12
```

Then **close that PowerShell window and open a new one**. PATH changes never
reach a window that was already open, which is the single most common reason
the next step appears to fail.

If `winget` is not available, download from
[python.org/downloads](https://www.python.org/downloads/) and tick
**"Add python.exe to PATH"** on the installer's first screen.

Confirm before continuing — you want 3.11 or newer, and a version number
rather than a Store window:

```powershell
python --version
```

## 2. Run the setup script

Open PowerShell in this folder (Shift + right-click the folder in Explorer →
"Open PowerShell window here") and run:

```powershell
powershell -ExecutionPolicy Bypass -File setup-windows.ps1
```

The `-ExecutionPolicy Bypass` part is needed because Windows blocks unsigned
scripts by default. It applies to this one command only and changes nothing
permanently.

The script creates a `.venv` folder here, installs four packages into it,
downloads the speech model (about 670 MB, once), puts the widget on your
desktop and in your Startup folder, and then runs a check.

Run the same command again after you pull or upgrade. It rewrites the Desktop
and Startup shortcuts, and an older install leaves them pointing at the entry
points that came before the widget.

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
  PASS  widget window (pywebview)
  PASS  WebView2 runtime
  PASS  Claude Code on PATH
```

Every line should say PASS. If one does not, it prints the command that fixes
it.

## 3a. Log Claude Code in once

The widget runs Claude Code headlessly for its live panels and the write-up,
on your subscription. The `claude` command keeps its own login, separate from
the desktop app, so do this once:

```powershell
claude
```

then type `/login` and follow it. Until then the widget records and
transcribes, and every panel that needs Claude shows that one instruction.

## 4. Wear headphones

Not optional, and not about sound quality. The tool records you and the call
as two separate tracks, which is what makes it able to tell who said what. On
speakers, the far end comes back through your microphone and lands on both
tracks, and that advantage is gone.

## Your first recording

The widget sits at the bottom right of your screen; setup also starts it at
login. Double-click **Meeting Notetaker** on the desktop if it is not there.

The strip shows what is next in your calendar. Expand it (the chevron, or
double-click the strip) and it pre-fills the meeting name and who is on it,
shows the sentence to say out loud, and keeps Start greyed out until you tick
that you have said it.

Press **Start recording**, take your call, press **Stop**. While the call
runs, the widget transcribes along and every couple of minutes shows what
has been agreed and what is worth asking; a panel shows what earlier calls
say about the person, and the ask box answers questions. None of it appears
in a screen share. At Stop the transcript finishes in seconds, the write-up
runs on its own, and the widget floats with the notes.

You can collapse or close the widget while it records. The recording is a
separate process and keeps going; the widget picks it back up.

### If something looks wrong

**Check setup** in the top-right corner runs every prerequisite check and
shows the result in the window, with the fix for anything that failed. The
same output is in the log it names, which is the thing to send if you want
help.

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
