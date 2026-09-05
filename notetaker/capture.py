"""Record the microphone and the system output as two separate tracks.

The two-track design is the single most valuable decision in this tool. A
mixed recording forces a model to guess who was speaking, and the best
diarisation models still get that wrong roughly one time in eight. Recording
each side to its own file makes attribution a property of the filesystem
instead of a prediction, so it is simply correct.

This only holds if the user wears headphones. On speakers, the remote voices
leak into the microphone and both tracks contain both parties. `mtg doctor`
says so, and so do the setup docs.

Nothing joins the call. Windows exposes the system's own output through
WASAPI loopback, so the audio is captured on this machine, at full quality,
before it ever reaches a third party.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAMPLE_RATE = 16_000   # everything downstream wants 16 kHz mono; capturing
CHANNELS = 1           # at source avoids a resample and saves ~6x the disk
BLOCK = 2_048
STOP_FLAG = "stop.flag"
STATE_FILE = "recording.json"


class CaptureError(RuntimeError):
    """Raised when recording cannot start, with a fix the user can act on."""


def _require_soundcard():
    """Import the audio backend lazily.

    Import-time failure would make every command, including `mtg doctor`,
    unusable on a machine that has not finished setup — which is exactly the
    machine that most needs the doctor to run.
    """
    try:
        import soundcard  # noqa: WPS433
    except ImportError as exc:
        raise CaptureError(
            "The audio library is not installed.\n"
            "  Fix:  pip install soundcard\n"
            "  Or rerun setup-windows.ps1, which installs everything."
        ) from exc
    return soundcard


@dataclass
class Track:
    name: str
    path: Path
    device: str
    frames: int = 0
    error: str = ""


def list_devices() -> dict[str, Any]:
    """Enumerate microphones and loopback devices."""
    sc = _require_soundcard()
    mics, loopbacks = [], []
    for mic in sc.all_microphones(include_loopback=True):
        entry = {"name": mic.name, "id": str(mic.id), "channels": mic.channels}
        (loopbacks if getattr(mic, "isloopback", False) else mics).append(entry)
    default_speaker = ""
    try:
        default_speaker = sc.default_speaker().name
    except Exception:
        pass
    return {"microphones": mics, "loopbacks": loopbacks, "default_speaker": default_speaker}


def _default_devices():
    """(mic, loopback) as soundcard objects; either may be None."""
    sc = _require_soundcard()
    mic = None
    try:
        mic = sc.default_microphone()
    except Exception:
        pass

    loopback = None
    try:
        loopback = sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)
    except Exception:
        # Fall back to the first loopback device of any output.
        for candidate in sc.all_microphones(include_loopback=True):
            if getattr(candidate, "isloopback", False):
                loopback = candidate
                break
    return mic, loopback


def _record_track(device, path: Path, stop: threading.Event, track: Track) -> None:
    """Stream one device to a WAV file until stopped.

    Frames are written as they arrive rather than accumulated, so memory use
    is flat regardless of how long the meeting runs and a crash costs only
    the last fraction of a second.
    """
    try:
        import numpy as np
    except ImportError:
        track.error = "numpy is not installed (pip install numpy)"
        return

    try:
        with wave.open(str(path), "wb") as out:
            out.setnchannels(CHANNELS)
            out.setsampwidth(2)          # 16-bit PCM
            out.setframerate(SAMPLE_RATE)
            with device.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                 blocksize=BLOCK) as rec:
                while not stop.is_set():
                    chunk = rec.record(numframes=BLOCK)
                    if chunk is None or len(chunk) == 0:
                        continue
                    if chunk.ndim > 1:           # downmix if the device insists
                        chunk = chunk.mean(axis=1)
                    clipped = np.clip(chunk, -1.0, 1.0)
                    out.writeframes((clipped * 32767).astype("<i2").tobytes())
                    track.frames += len(chunk)
    except Exception as exc:                     # one dead track must not
        track.error = str(exc)                   # end the whole recording


def repair_wav(path: Path) -> bool:
    """Fix RIFF sizes on a file whose writer was killed mid-recording.

    The wave module only stamps the length on close. If the machine slept or
    the process died, the header claims zero frames and every player reports
    an empty file even though the audio is all there. Recomputing the two
    size fields from the real file length recovers it.
    """
    try:
        size = path.stat().st_size
        if size < 44:
            return False
        with path.open("r+b") as fh:
            if fh.read(4) != b"RIFF":
                return False
            fh.seek(4)
            declared = struct.unpack("<I", fh.read(4))[0]
            if declared == size - 8:
                return False                      # header is already correct
            fh.seek(4)
            fh.write(struct.pack("<I", size - 8))
            fh.seek(40)
            fh.write(struct.pack("<I", size - 44))
        return True
    except (OSError, struct.error):
        return False


def start_recording(meeting_dir: Path, video: bool = False) -> dict[str, Any]:
    """Record until a stop flag appears. Blocks; run in a child process.

    Returns the state dict that was written to recording.json.
    """
    meeting_dir = Path(meeting_dir)
    meeting_dir.mkdir(parents=True, exist_ok=True)
    flag = meeting_dir / STOP_FLAG
    flag.unlink(missing_ok=True)

    mic, loopback = _default_devices()
    if mic is None and loopback is None:
        raise CaptureError(
            "No microphone and no system-audio device were found.\n"
            "  Fix:  check Windows Settings > System > Sound, then run  mtg doctor"
        )

    tracks: list[Track] = []
    threads: list[threading.Thread] = []
    stop = threading.Event()

    if loopback is not None:
        tracks.append(Track("system", meeting_dir / "system.wav", loopback.name))
    if mic is not None:
        tracks.append(Track("mic", meeting_dir / "mic.wav", mic.name))

    state = {
        "pid": os.getpid(),
        "started_at": time.time(),
        "tracks": [{"name": t.name, "path": str(t.path), "device": t.device} for t in tracks],
        "video": bool(video),
        "sample_rate": SAMPLE_RATE,
    }
    (meeting_dir / STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")

    devices = {"system": loopback, "mic": mic}
    for track in tracks:
        thread = threading.Thread(
            target=_record_track,
            args=(devices[track.name], track.path, stop, track),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    video_proc = _start_video(meeting_dir) if video else None

    try:
        while not flag.exists():
            time.sleep(0.2)
            if all(t.error for t in tracks):      # every track failed
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
        if video_proc is not None:
            _stop_video(video_proc)
        flag.unlink(missing_ok=True)

    state["ended_at"] = time.time()
    state["duration_seconds"] = round(state["ended_at"] - state["started_at"], 1)
    state["results"] = [
        {"name": t.name, "path": str(t.path), "frames": t.frames, "error": t.error}
        for t in tracks
    ]
    (meeting_dir / STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def _start_video(meeting_dir: Path):
    """Screen capture is optional and needs ffmpeg; audio never does."""
    import shutil

    if not shutil.which("ffmpeg"):
        return None
    grabber = "gdigrab" if sys.platform == "win32" else "x11grab"
    target = "desktop" if sys.platform == "win32" else os.environ.get("DISPLAY", ":0")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", grabber, "-framerate", "6", "-i", target,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
        str(meeting_dir / "screen.mp4"),
    ]
    try:
        return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def _stop_video(proc) -> None:
    """Ask ffmpeg to finish so the container is valid; kill only as a last resort."""
    try:
        if proc.stdin:
            proc.stdin.write(b"q")
            proc.stdin.flush()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()


def is_recording(meeting_dir: Path) -> bool:
    state_path = Path(meeting_dir) / STATE_FILE
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return "ended_at" not in state


def stop_recording(meeting_dir: Path, timeout: float = 30.0) -> list[str]:
    """Signal the recorder to stop and wait for it to finalise its files.

    A flag file rather than a signal: Windows has no SIGINT to send to an
    unrelated process, and CTRL_BREAK only reaches a shared console. A file
    works identically everywhere and cannot be missed.
    """
    meeting_dir = Path(meeting_dir)
    state_path = meeting_dir / STATE_FILE
    if not state_path.exists():
        return []

    (meeting_dir / STOP_FLAG).write_text("stop", encoding="utf-8")

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if "ended_at" in state:
                break
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.25)

    (meeting_dir / STOP_FLAG).unlink(missing_ok=True)

    produced: list[str] = []
    for candidate in ("mic.wav", "system.wav", "screen.mp4"):
        path = meeting_dir / candidate
        if path.exists() and path.stat().st_size > 44:
            if path.suffix == ".wav":
                repair_wav(path)
            produced.append(str(path))
    return produced


def audio_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as fh:
            return fh.getnframes() / float(fh.getframerate() or SAMPLE_RATE)
    except Exception:
        return 0.0
