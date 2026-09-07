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

from . import log

_log = log.get("capture")

SAMPLE_RATE = 16_000   # everything downstream wants 16 kHz mono; capturing
CHANNELS = 1           # at source avoids a resample and saves ~6x the disk
BLOCK = 2_048
BUFFER_SECONDS = 1.0   # WASAPI capture buffer, Windows only. The 128 ms default
                       # overflowed whenever the reader stalled, and lost audio.
GAP_TOLERANCE = 0.1    # a pause in delivery shorter than this is jitter, not a stall
SETTLE = 1.5           # never fill silence closer to now than this: a packet
                       # recovered from the buffer can be BUFFER_SECONDS old
STOP_FLAG = "stop.flag"
STATE_FILE = "recording.json"


class CaptureError(RuntimeError):
    """Raised when recording cannot start, with a fix the user can act on."""


_clock = time.perf_counter   # sub-millisecond on Windows; monotonic() is not before 3.13

try:
    import numpy as np
except ImportError:          # the module must still import, for `mtg doctor`
    np = None

# IAudioCaptureClient::GetBuffer flags, and its "nothing to read" success code.
_DISCONTINUITY, _SILENT, _TIMESTAMP_ERROR = 0x1, 0x2, 0x4
_BUFFER_EMPTY = 0x08890001


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
    except Exception as exc:
        # Installed, but its native backend refused to load — no audio
        # subsystem, a broken driver, a missing runtime.
        raise CaptureError(
            f"The audio library is installed but could not start: {exc}\n"
            "  Check Windows Settings > System > Sound has an active output "
            "device,\n  then run  mtg doctor"
        ) from exc
    return soundcard


@dataclass
class Track:
    name: str
    path: Path
    device: str
    frames: int = 0
    error: str = ""
    timing: str = ""           # "wasapi": placed by timestamp; "sequential": appended
    lead: float = 0.0          # seconds of silence before the first real frame
    filled: float = 0.0        # seconds of silence standing in for lost or paused audio
    discontinuities: int = 0   # packets WASAPI flagged as following a gap
    overlap: float = 0.0       # seconds a packet was stamped earlier than the file end


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


def _record_track(device, path: Path, stop: threading.Event, track: Track,
                  t0: float | None = None) -> None:
    """Stream one device to a WAV file until stopped.

    Frames are written as they arrive rather than accumulated, so memory use
    is flat regardless of how long the meeting runs and a crash costs only
    the last fraction of a second.

    Two things make a plain append loop drift off the wall clock, and both
    were measured on the Latitude 3440:

    * The devices do not start together. The digital microphone array takes
      one to two seconds to open its WASAPI stream; the loopback opens at
      once. Appended naively, every "Me" line would sort early against
      "Them" in the merged transcript.
    * The microphone stream pauses for a moment every ten seconds or so at
      idle, and constantly under CPU load. soundcard's record() fills a pause
      with wall-clock silence and then hands over the device's real frames
      for the same interval, so the file gains time it never lived: 1% long
      at idle, 26% long under six CPU burners. The loopback, when nothing is
      playing, delivers nothing at all and comes out as invented silence.

    So on Windows this does not use soundcard's record() loop. WASAPI stamps
    every capture packet with the QueryPerformanceCounter time of its first
    sample, on the same counter perf_counter reads, and each packet is placed
    in the file at that position relative to the shared start `t0`. A packet
    that arrives after a pause, or that WASAPI flags as following a gap, goes
    where its stamp says and the interval before it, audio the engine lost or
    a device that was paused, becomes silence. A packet that arrives on time
    is appended as is. Nothing is ever deleted and no sample value is ever
    changed; the only synthetic content is silence standing in for time in
    which the device produced nothing. Both files start at `t0` and end at
    the stop instant, so they line up. Everywhere else (the fake device in
    the tests, other platforms) the plain block loop runs, with the lead
    measured before the first read.
    """
    if np is None:
        track.error = "numpy is not installed (pip install numpy)"
        return

    origin = _clock() if t0 is None else t0
    windows = sys.platform == "win32"
    blocksize = int(BUFFER_SECONDS * SAMPLE_RATE) if windows else BLOCK
    try:
        with wave.open(str(path), "wb") as out:
            out.setnchannels(CHANNELS)
            out.setsampwidth(2)          # 16-bit PCM
            out.setframerate(SAMPLE_RATE)
            with device.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                 blocksize=blocksize) as rec:
                source = _WasapiSource.open(rec, CHANNELS) if windows else None
                if windows and source is None and type(rec).__module__.startswith("soundcard"):
                    _log.warning("WASAPI packet timing unavailable (soundcard internals "
                                 "changed?); %s will be timed sequentially", track.name)
                if source is not None:
                    track.timing = "wasapi"
                    _record_packets(source, out, stop, track, origin)
                else:
                    track.timing = "sequential"
                    _record_blocks(rec, out, stop, track, origin)
    except Exception as exc:                     # one dead track must not
        track.error = str(exc)                   # end the whole recording
        _log.exception("track %s failed", track.name)


class _Timeline:
    """Writes audio into a WAV at the position its timestamps give it.

    Frames go in with writeframesraw: the wave module's writeframes seeks
    back to patch the header on every call, four system calls per 10 ms
    packet, and one of those seeks failed with EINVAL on the laptop under
    load and killed a track. The header is patched once, at close; if the
    recorder dies first, stop_recording's repair_wav puts it right from the
    file size. A flush every FLUSH_SECONDS keeps the live transcriber's view
    of the file current.

    A failed write skips that packet and counts it; it never ends the track.
    """

    FLUSH_SECONDS = 0.5

    def __init__(self, out, origin: float):
        self.out = out
        self.origin = origin
        self.frames = 0          # frames in the file so far, silence included
        self.filled = 0          # silence standing in for lost or paused audio
        self.started = False     # has any real audio been written yet
        self.write_errors = 0
        self._last_flush = _clock()

    def position(self, stamp: float) -> int:
        """File position, in frames, of an instant on the shared clock."""
        return int(round((stamp - self.origin) * SAMPLE_RATE))

    def _write(self, data: bytes, frames: int) -> bool:
        try:
            self.out.writeframesraw(data)
        except OSError as exc:
            self.write_errors += 1
            if self.write_errors in (1, 10, 100, 1000):
                _log.warning("write failed (%d so far): %s", self.write_errors, exc)
            return False
        self.frames += frames
        now = _clock()
        if now - self._last_flush >= self.FLUSH_SECONDS:
            self._last_flush = now
            try:
                self.out._file.flush()
            except Exception:
                pass
        return True

    def fill_to(self, frames: int) -> None:
        """Extend the file with silence up to a position; never shortens."""
        gap = frames - self.frames
        if gap > 0 and self._write(b"\x00\x00" * gap, gap) and self.started:
            self.filled += gap

    def append(self, samples) -> None:
        clipped = np.clip(samples, -1.0, 1.0)
        self._write((clipped * 32767).astype("<i2").tobytes(), len(samples))
        self.started = True


class _WasapiSource:
    """Capture packets straight from soundcard's WASAPI client, with stamps.

    soundcard's own record() is what invents silence, so this reads the
    packets it wraps: IAudioCaptureClient::GetBuffer, including the QPC
    position soundcard discards. It relies on private attributes of
    soundcard 0.4.x; if they are missing, open() returns None and the block
    loop runs instead, which records correctly but cannot keep time.
    """

    def __init__(self, client, available, release, check, ffi, channels: int):
        self._client = client
        self._available = available
        self._release = release
        self._check = check
        self._ffi = ffi
        self._channels = channels

    @classmethod
    def open(cls, rec, channels: int):
        # Look before importing: a fake recorder in the tests has none of
        # these, and importing soundcard cold takes long enough to matter.
        if not all(hasattr(rec, name) for name in
                   ("_ppCaptureClient", "_capture_available_frames", "_capture_release")):
            return None
        try:
            from soundcard import mediafoundation as mf

            return cls(rec._ppCaptureClient, rec._capture_available_frames,
                       rec._capture_release, mf._com.check_error, mf._ffi, channels)
        except (ImportError, AttributeError):
            return None

    def read(self):
        """(samples, flags, stamp) for the next packet, or None if none is waiting.

        `stamp` is the perf_counter-scale time of the first sample, or None
        when WASAPI says its timestamp is unreliable.
        """
        if self._available() == 0:
            return None
        ffi = self._ffi
        data = ffi.new("BYTE**")
        count = ffi.new("UINT32*")
        flags = ffi.new("DWORD*")
        devpos = ffi.new("UINT64*")
        qpc = ffi.new("UINT64*")
        hr = self._client[0][0].lpVtbl.GetBuffer(self._client[0], data, count, flags,
                                                 devpos, qpc)
        if hr == _BUFFER_EMPTY:          # a success code: nothing to read after all
            return None
        self._check(hr)
        n = int(count[0])
        if n == 0:
            return None
        samples = np.frombuffer(ffi.buffer(data[0], n * 4 * self._channels),
                                dtype=np.float32).copy()
        fl = int(flags[0])
        stamp = None if fl & _TIMESTAMP_ERROR else qpc[0] / 1e7   # 100 ns units
        self._release(n)
        if fl & _SILENT:                 # the buffer holds nothing meaningful
            samples[:] = 0.0
        if self._channels > 1:
            samples = samples.reshape(-1, self._channels).mean(axis=1)
        return samples, fl, stamp


def _record_packets(source, out, stop: threading.Event, track: Track, origin: float) -> None:
    """The Windows loop: place every packet at its stamped position."""
    tl = _Timeline(out, origin)
    state = {"last_arrival": _clock(), "first": True, "overlap": 0}

    def place(packet, now: float) -> None:
        samples, flags, stamp = packet
        first = state["first"]
        after_gap = bool(flags & _DISCONTINUITY) and not first   # always set on the first
        if after_gap:
            track.discontinuities += 1
        if first or after_gap or now - state["last_arrival"] > GAP_TOLERANCE:
            # WASAPI occasionally marks a stamp unreliable; then the packet
            # cannot have begun later than one packet before it was read.
            anchor = stamp if stamp is not None else now - len(samples) / SAMPLE_RATE
            pos = tl.position(anchor)
            if pos > tl.frames:
                tl.fill_to(pos)
            elif pos < tl.frames - SAMPLE_RATE // 100:      # over 10 ms early: keep
                state["overlap"] += tl.frames - pos          # the audio, note it
        if first:
            state["first"] = False
            track.lead = tl.frames / SAMPLE_RATE
        tl.append(samples)
        state["last_arrival"] = now
        track.frames = tl.frames

    try:
        while not stop.is_set():
            packet = source.read()
            now = _clock()
            if packet is None:
                # Nothing waiting. A paused device (the loopback with nothing
                # playing) still owes the file its silence, but only up to
                # SETTLE ago: a packet recovered from the buffer can be that old.
                tl.fill_to(tl.position(now - SETTLE))
                time.sleep(0.003)
                continue
            place(packet, now)
        # The flag says finish, not discard: take what the engine still holds,
        # at most one buffer's worth of packets.
        for _ in range(int(BUFFER_SECONDS * 100) + 10):
            packet = source.read()
            if packet is None:
                break
            place(packet, _clock())
        tl.fill_to(tl.position(_clock()))    # every track ends at the stop instant
    finally:
        track.frames = tl.frames
        track.filled = tl.filled / SAMPLE_RATE
        track.overlap = state["overlap"] / SAMPLE_RATE
        if tl.write_errors and not track.error:
            track.error = f"{tl.write_errors} packet(s) could not be written"


def _record_blocks(rec, out, stop: threading.Event, track: Track, origin: float) -> None:
    """The plain loop: append blocks as soundcard hands them over.

    Used by the fake device in the tests and on platforms without the WASAPI
    packet path. It measures the lead from just before the first read, which
    the first sample cannot predate, and otherwise trusts the device's rate.
    """
    tl = _Timeline(out, origin)
    before = _clock()
    first = True
    while not stop.is_set():
        chunk = rec.record(numframes=BLOCK)
        if chunk is None or len(chunk) == 0:
            continue
        if chunk.ndim > 1:                       # downmix if the device insists
            chunk = chunk.mean(axis=1)
        if first:
            first = False
            tl.fill_to(tl.position(before))
            track.lead = tl.frames / SAMPLE_RATE
        tl.append(chunk)
        track.frames = tl.frames


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
    _log.info("devices: mic=%r loopback=%r", getattr(mic, "name", None),
              getattr(loopback, "name", None))
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
    t0 = _clock()                                # one origin for every track
    for track in tracks:
        thread = threading.Thread(
            target=_record_track,
            args=(devices[track.name], track.path, stop, track, t0),
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
    _log.info("stopped after %ss; %s", state["duration_seconds"],
              {t.name: (t.timing, t.frames, round(t.lead, 3), round(t.filled, 3),
                        t.discontinuities, round(t.overlap, 3)) for t in tracks})
    state["results"] = [
        {"name": t.name, "path": str(t.path), "frames": t.frames, "error": t.error,
         "timing": t.timing, "lead_seconds": round(t.lead, 3),
         "filled_seconds": round(t.filled, 3), "discontinuities": t.discontinuities,
         "overlap_seconds": round(t.overlap, 3)}
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
