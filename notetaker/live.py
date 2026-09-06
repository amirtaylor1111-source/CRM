"""Transcribe a meeting while it is still being recorded.

The recorder writes mic.wav and system.wav continuously. This reads what has
been appended since its last pass, transcribes it through the same Parakeet
and VAD chain `transcribe.py` uses after a call, and keeps `transcript.md`
and `transcript.json` up to date in exactly the format `/notes` reads, so a
brief can be written while the call is still going.

Each pass overlaps the previous one by a few seconds so a word on the
boundary is heard with its context. The bookkeeping that makes that safe:

* `committed` is the time up to which a track is final. A pass reads from
  `committed - OVERLAP` to the end of the file.
* A segment that ends before `committed` is a repeat and is dropped. One
  that starts before `committed` and ends after it is VAD joining speech
  across the boundary; it is split at `committed` using the model's
  per-token timestamps, so the words already on record are not repeated
  and the new ones are not lost.
* The last segment of a pass is held back if it ends within `TAIL` of the
  end of the audio, because VAD may have cut it mid-word. `committed` moves
  to its start and the next pass hears all of it.
* Between passes, `committed` never advances into the last `TAIL_SILENCE`
  seconds of the file: speech too short for VAD to emit yet must still be
  in front of the line when it is heard whole.

If a pass raises, the error is kept, later passes still run, and `finish()`
refuses so the caller falls back to the full transcription of the files.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import hardware, log
from . import transcribe as tr
from .schema import utcnow

_log = log.get("live")

SAMPLE_RATE = 16_000
HEADER_BYTES = 44          # a canonical PCM WAV header; the recorder writes one
INTERVAL = 30.0            # seconds between passes
OVERLAP = 3.0              # seconds re-read before the committed point
JOIN_TOLERANCE = 0.5       # a segment starting this far before the line was
                           # joined by VAD; anything closer is the same segment
TAIL = 1.0                 # a segment ending this close to the end is held back
TAIL_SILENCE = 2.0         # committed never enters the last stretch of audio
MIN_NEW_AUDIO = 2.0        # skip a pass with less than this to transcribe
MAX_PASS_SECONDS = 120.0   # one pass never takes more than this much audio; a
                           # widget adopting a long recording catches up in steps
SPEAKERS = {"mic": "Me", "system": "Them"}

try:
    import numpy as np
except ImportError:        # the module must import for `mtg doctor`
    np = None


class LiveError(RuntimeError):
    """The live transcript cannot be trusted; transcribe the files instead."""


@dataclass
class LiveSegment(tr.Segment):
    tokens: list[tuple[float, str]] = field(default_factory=list)   # (time, token)


TranscribeFn = Callable[["np.ndarray"], list[LiveSegment]]


def read_new_audio(path: Path, start_seconds: float):
    """PCM from `start_seconds` to the end of a WAV still being written.

    The length comes from the file size, not the header: the header's length
    fields are only right once the recorder closes the file. The recorder
    flushes its writer twice a second, so the file on disk is never more
    than that far behind; verified on the laptop with the recorder in
    another process. Python opens files with read and write sharing on
    Windows, so reading while the recorder holds the file open is fine.
    """
    size = path.stat().st_size
    frames = max(0, (size - HEADER_BYTES) // 2)
    start = int(start_seconds * SAMPLE_RATE)
    if frames <= start:
        return None
    with path.open("rb") as fh:
        fh.seek(HEADER_BYTES + start * 2)
        raw = fh.read((frames - start) * 2)
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


# --- the model ---------------------------------------------------------------

_PIPELINE = None
_PIPELINE_LOCK = threading.Lock()


def _pipeline(threads: int):
    """Parakeet with VAD and timestamps, loaded once per process."""
    global _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is None:
            import onnx_asr

            sess_options = None
            if threads:
                import onnxruntime as ort

                sess_options = ort.SessionOptions()
                sess_options.intra_op_num_threads = threads
            model = onnx_asr.load_model(hardware.ENGINES["parakeet"]["model"],
                                        quantization="int8", sess_options=sess_options)
            _PIPELINE = model.with_vad(onnx_asr.load_vad("silero")).with_timestamps()
        return _PIPELINE


def inference_threads() -> int:
    """Leave the call's own software most of the machine."""
    return max(1, hardware._threads_for(hardware.detect()) // 2)


def parakeet(audio, threads: int = 0) -> list[LiveSegment]:
    """Transcribe an array of 16 kHz mono float32 audio."""
    results = _pipeline(threads).recognize(audio, sample_rate=SAMPLE_RATE)
    results = [results] if hasattr(results, "text") else list(results)
    out: list[LiveSegment] = []
    for item in results:
        seg = tr.segment_from_result(item)
        if seg is None:
            continue
        times = list(getattr(item, "timestamps", None) or [])
        toks = list(getattr(item, "tokens", None) or [])
        tokens = list(zip(times, toks)) if times and len(times) == len(toks) else []
        if tokens and tokens[0][0] < seg.start - 0.5:      # relative to the segment
            tokens = [(t + seg.start, tok) for t, tok in tokens]
        out.append(LiveSegment(seg.start, seg.end, seg.text, confidence=seg.confidence,
                               low_confidence=seg.low_confidence, tokens=tokens))
    return out


def _detokenize(tokens: Iterable[str]) -> str:
    """Join subword tokens back into text.

    Parakeet's tokens carry their own word boundaries, as a leading space
    (" M", "ont", "y") or SentencePiece's "▁"; tokens with neither are
    whole words.
    """
    toks = list(tokens)
    if any(t.startswith(" ") or "▁" in t for t in toks):
        return " ".join("".join(toks).replace("▁", " ").split())
    return " ".join(t.strip() for t in toks if t.strip())


def preload(threads: int | None = None) -> None:
    """Load the model now, so the first pass of a call is not the slow one."""
    _pipeline(inference_threads() if threads is None else threads)


def split_at(seg: LiveSegment, at: float) -> LiveSegment | None:
    """The part of a segment from `at` on, or None if nothing new remains.

    Without token timestamps the whole segment is kept from `at`: a few
    repeated words are a smaller harm than words missing from the record.
    """
    if seg.end <= at:
        return None
    if not seg.tokens:
        return LiveSegment(at, seg.end, seg.text, confidence=seg.confidence,
                           low_confidence=seg.low_confidence)
    kept = [(t, tok) for t, tok in seg.tokens if t >= at]
    text = _detokenize(tok for _, tok in kept)
    if not text:
        return None
    return LiveSegment(kept[0][0], seg.end, text, confidence=seg.confidence,
                       low_confidence=seg.low_confidence, tokens=kept)


# --- the transcriber -------------------------------------------------------


@dataclass
class _TrackState:
    name: str
    path: Path
    committed: float = 0.0
    segments: list[LiveSegment] = field(default_factory=list)


class LiveTranscriber:
    def __init__(self, meeting_dir: Path, vocabulary: Iterable[str] = (),
                 transcribe_fn: TranscribeFn | None = None, threads: int | None = None):
        if np is None:
            raise LiveError("numpy is not installed (pip install numpy)")
        self.meeting_dir = Path(meeting_dir)
        self.vocabulary = list(vocabulary)
        self.threads = inference_threads() if threads is None else threads
        self._transcribe = transcribe_fn or (lambda audio: parakeet(audio, self.threads))
        self.tracks = {name: _TrackState(name, self.meeting_dir / f"{name}.wav")
                       for name in SPEAKERS}
        self.error = ""
        self.passes = 0
        self.names_corrected = 0
        self._speech = 0.0
        self._lock = threading.Lock()

    # --- reads --------------------------------------------------------------

    @property
    def segments(self) -> list[LiveSegment]:
        return [s for t in self.tracks.values() for s in t.segments]

    def seconds(self) -> float:
        """Audio committed so far on the longest track."""
        return max((t.committed for t in self.tracks.values()), default=0.0)

    def new_speech_seconds(self) -> float:
        return self._speech

    def reset_speech(self) -> None:
        self._speech = 0.0

    # --- passes -------------------------------------------------------------

    def tick(self, final: bool = False) -> int:
        """One pass over every track. Returns how many segments were added."""
        added = 0
        with self._lock:
            for state in self.tracks.values():
                if not state.path.exists():
                    continue
                try:
                    added += self._pass(state, final)
                except Exception as exc:
                    self.error = f"{type(exc).__name__}: {exc}"
                    _log.exception("live pass failed on %s", state.name)
            self.passes += 1
            if added or final:
                try:
                    self._write(live=not final)
                except Exception as exc:          # a write failure is a failure too
                    self.error = f"{type(exc).__name__}: {exc}"
                    _log.exception("live transcript write failed")
        return added

    def resume(self) -> int:
        """Pick up where a previous widget left this meeting's live transcript.

        Reads transcript.json if it was written live, restores its segments,
        and moves each track's line to the end of its last segment, so a
        reopened widget carries on rather than transcribing the call again.
        Returns the number of segments restored.
        """
        import json

        path = self.meeting_dir / "transcript.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not data.get("meta", {}).get("live"):
            return 0
        by_speaker = {label: name for name, label in SPEAKERS.items()}
        restored = 0
        with self._lock:
            for raw in data.get("segments", []):
                name = by_speaker.get(raw.get("speaker", ""))
                if name is None:
                    continue
                seg = LiveSegment(float(raw["start"]), float(raw["end"]), str(raw["text"]),
                                  speaker=raw.get("speaker", ""),
                                  confidence=float(raw.get("confidence") or 0.0),
                                  low_confidence=bool(raw.get("low_confidence")),
                                  corrections=list(raw.get("corrections") or []))
                state = self.tracks[name]
                state.segments.append(seg)
                state.committed = max(state.committed, seg.end)
                restored += 1
            self.names_corrected = int(data.get("meta", {}).get("names_corrected") or 0)
        return restored

    def finish(self) -> int:
        """The last pass, with nothing held back. Raises if the call had errors."""
        if self.error:
            raise LiveError(f"live transcription failed during the call: {self.error}")
        self.tick(final=True)
        if self.error:
            raise LiveError(f"live transcription failed at the end: {self.error}")
        return len(self.segments)

    def backlog(self) -> float:
        """Seconds of audio on disk past the furthest committed point."""
        most = 0.0
        for state in self.tracks.values():
            try:
                size = state.path.stat().st_size
            except OSError:
                continue
            on_disk = max(0, (size - HEADER_BYTES) // 2) / SAMPLE_RATE
            most = max(most, on_disk - state.committed)
        return most

    def _pass(self, state: _TrackState, final: bool) -> int:
        start = max(0.0, state.committed - OVERLAP)
        audio = read_new_audio(state.path, start)
        if audio is None:
            return 0
        if not final and len(audio) > MAX_PASS_SECONDS * SAMPLE_RATE:
            audio = audio[: int(MAX_PASS_SECONDS * SAMPLE_RATE)]
        end = start + len(audio) / SAMPLE_RATE
        if not final and end - state.committed < MIN_NEW_AUDIO:
            return 0

        kept: list[LiveSegment] = []
        for seg in self._transcribe(audio):
            seg.start += start
            seg.end += start
            seg.tokens = [(t + start, tok) for t, tok in seg.tokens]
            if seg.end <= state.committed + 0.05:            # already on record
                continue
            if seg.start < state.committed - JOIN_TOLERANCE:  # joined across the line
                seg = split_at(seg, state.committed)
                if seg is None:
                    continue
            kept.append(seg)

        held = None
        if kept and not final and kept[-1].end > end - TAIL:
            held = kept.pop()                                # maybe cut mid-word

        if kept:
            self.names_corrected += tr.correct_names(kept, self.vocabulary)
            state.segments.extend(kept)
            self._speech += sum(s.end - s.start for s in kept)

        if final and end >= (audio_end := start + len(audio) / SAMPLE_RATE):
            state.committed = end
        elif final:
            state.committed = audio_end
        elif held is not None:
            state.committed = max(state.committed, held.start)
        else:
            state.committed = max(state.committed,
                                  kept[-1].end if kept else 0.0,
                                  end - TAIL_SILENCE)
        return len(kept)

    # --- files --------------------------------------------------------------

    def _write(self, live: bool) -> None:
        per_track = {name: list(t.segments) for name, t in self.tracks.items() if t.segments}
        segments = tr.merge_tracks(per_track, SPEAKERS)
        choice = hardware.ENGINES["parakeet"]
        flagged = sum(1 for s in segments if s.low_confidence)
        meta = {
            "generated_at": utcnow(),
            "engine": "onnx-asr",
            "model": choice["model"],
            "expected_accuracy": choice["wer"],
            "duration": tr.hhmmss(self.seconds()),
            "tracks": ", ".join(sorted(n for n, t in self.tracks.items() if t.path.exists())),
            "speaker_method": "separate audio tracks (attribution is exact)",
            "segments": len(segments),
            "low_confidence_segments": flagged,
            "names_corrected": self.names_corrected,
            "live": live,
        }
        tr.write_transcript(self.meeting_dir, segments, meta)


# --- the worker process ------------------------------------------------------
#
# Loading the model holds the interpreter lock for seconds at a time (11.7 s
# on the Latitude, in stretches of up to 7 s), which froze the widget's API
# and, in an early test, starved the recorder. So the model never loads in
# the widget process: each call gets a worker, `python -m notetaker.live`,
# that owns the model and answers one-line JSON commands on its pipes. The
# widget talks to it through LiveProcess, which has the shape the Session
# expects. If the worker dies, the Session falls back to transcribing the
# files at Stop, in a worker of its own.

import json
import os
import subprocess
import sys

WORKER_OPEN_TIMEOUT = 300.0       # the model may still be downloading
WORKER_TICK_TIMEOUT = 240.0
WORKER_FINISH_TIMEOUT = 900.0


def _transcriber_from_env():
    """Tests point MTG_LIVE_TRANSCRIBER at "module:factory" for a fake."""
    spec = os.environ.get("MTG_LIVE_TRANSCRIBER", "")
    if not spec:
        return None
    module_name, _, attr = spec.partition(":")
    import importlib

    factory = getattr(importlib.import_module(module_name), attr)
    return factory()


def worker_main(stdin=None, stdout=None) -> int:
    """Serve commands for one meeting until told to quit."""
    protocol_out = stdout or sys.stdout
    if stdout is None:
        sys.stdout = sys.stderr           # library chatter must not reach the protocol
    stdin = stdin or sys.stdin

    def reply(**payload):
        protocol_out.write(json.dumps(payload) + "\n")
        protocol_out.flush()

    transcriber = None
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            reply(ok=False, error="bad command")
            continue
        name = cmd.get("cmd")
        try:
            if name == "open":
                fake = _transcriber_from_env()
                transcriber = LiveTranscriber(Path(cmd["meeting_dir"]), cmd.get("vocabulary", ()),
                                              transcribe_fn=fake,
                                              threads=int(cmd.get("threads") or 0) or None)
                restored = transcriber.resume() if cmd.get("resume") else 0
                if fake is None:
                    preload(transcriber.threads)
                reply(ok=True, restored=restored)
            elif name == "tick":
                if cmd.get("reset_speech"):
                    transcriber.reset_speech()
                added = transcriber.tick()
                reply(ok=True, added=added, count=len(transcriber.segments),
                      seconds=transcriber.seconds(), speech=transcriber.new_speech_seconds(),
                      backlog=transcriber.backlog(), error=transcriber.error)
            elif name == "reset_speech":
                transcriber.reset_speech()
                reply(ok=True)
            elif name == "finish":
                try:
                    count = transcriber.finish()
                    reply(ok=True, count=count)
                except LiveError as exc:
                    reply(ok=False, error=str(exc))
            elif name == "transcribe_files":
                fake = _transcriber_from_env()
                if fake is not None:               # the tests' stand-in for the model
                    whole = LiveTranscriber(Path(cmd["meeting_dir"]), cmd.get("vocabulary", ()),
                                            transcribe_fn=fake, threads=1)
                    whole.tick(final=True)
                else:
                    tr.transcribe_meeting(Path(cmd["meeting_dir"]),
                                          vocabulary=cmd.get("vocabulary", ()),
                                          progress=lambda m: None)
                reply(ok=True)
            elif name == "quit":
                reply(ok=True)
                return 0
            else:
                reply(ok=False, error=f"unknown command {name!r}")
        except Exception as exc:
            _log.exception("worker command %s failed", name)
            reply(ok=False, error=f"{type(exc).__name__}: {exc}")
    return 0


class LiveProcess:
    """The Session's handle on a live transcriber running in its own process.

    Same shape as LiveTranscriber for what the Session uses: tick(),
    finish(), count(), seconds(), new_speech_seconds(), reset_speech(),
    resume(), error. Every call is synchronous with a timeout; a worker that
    stops answering is treated as dead and `error` says so.
    """

    def __init__(self, meeting_dir: Path, vocabulary: Iterable[str] = (), threads: int | None = None,
                 python: str | None = None):
        self.meeting_dir = Path(meeting_dir)
        self.vocabulary = list(vocabulary)
        self.threads = threads
        self.error = ""
        self._count = 0
        self._seconds = 0.0
        self._speech = 0.0
        self._lock = threading.Lock()
        self._proc = None
        self._opened = False
        self._reset_pending = False
        self._backlog = 0.0
        self._python = python or _console_python()

    # --- process ---------------------------------------------------------------

    def _spawn(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(
            [self._python, "-m", "notetaker.live", str(self.meeting_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, creationflags=flags,
            cwd=str(self.meeting_dir.parent.parent))

    def _call(self, timeout: float, **cmd) -> dict:
        """One command, one reply. Never raises; failures land in `error`."""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self.error = self.error or "the live transcriber process is not running"
                return {"ok": False, "error": self.error}
            try:
                self._proc.stdin.write(json.dumps(cmd) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self.error = f"live transcriber pipe: {exc}"
                return {"ok": False, "error": self.error}
            reply: dict = {}

            def read():
                try:
                    line = self._proc.stdout.readline()
                    reply.update(json.loads(line) if line.strip() else {"ok": False, "error": "worker exited"})
                except Exception as exc:
                    reply.update({"ok": False, "error": f"bad reply: {exc}"})

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            reader.join(timeout)
            if reader.is_alive():
                self.error = f"the live transcriber did not answer {cmd.get('cmd')} within {int(timeout)} s"
                self.close(kill=True)
                return {"ok": False, "error": self.error}
            if not reply.get("ok") and reply.get("error"):
                self.error = str(reply["error"])
            return reply

    def open(self, resume: bool = False) -> bool:
        try:
            self._spawn()
        except OSError as exc:
            self.error = f"could not start the live transcriber: {exc}"
            return False
        reply = self._call(WORKER_OPEN_TIMEOUT, cmd="open", meeting_dir=str(self.meeting_dir),
                           vocabulary=self.vocabulary, threads=self.threads or 0, resume=resume)
        self._opened = bool(reply.get("ok"))
        return self._opened

    def close(self, kill: bool = False) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if not kill and proc.poll() is None:
                proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                proc.stdin.flush()
                proc.wait(timeout=5)
        except Exception:
            pass
        if proc.poll() is None:
            proc.kill()

    # --- the transcriber's shape -------------------------------------------------

    def resume(self) -> int:
        return 0                       # handled by open(resume=True)

    def tick(self, final: bool = False) -> int:
        reset, self._reset_pending = self._reset_pending, False
        reply = self._call(WORKER_TICK_TIMEOUT, cmd="tick", reset_speech=reset)
        if reply.get("ok"):
            self._count = int(reply.get("count") or 0)
            self._seconds = float(reply.get("seconds") or 0.0)
            self._speech = float(reply.get("speech") or 0.0)
            self._backlog = float(reply.get("backlog") or 0.0)
            self.error = str(reply.get("error") or "")
            return int(reply.get("added") or 0)
        # A failed tick leaves the last good reading in place, and the caller
        # uses the backlog to decide whether to tick again at once. Clear it,
        # or a dead worker with a high last reading spins the caller's loop.
        self._backlog = 0.0
        return 0

    def backlog(self) -> float:
        """Seconds of audio the worker has not reached yet."""
        return self._backlog

    def finish(self) -> int:
        reply = self._call(WORKER_FINISH_TIMEOUT, cmd="finish")
        self.close()
        if not reply.get("ok"):
            raise LiveError(str(reply.get("error") or "live transcription failed"))
        self._count = int(reply.get("count") or 0)
        return self._count

    def transcribe_files(self) -> None:
        """The fallback, in a worker: transcribe the finished files whole."""
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()
        reply = self._call(WORKER_FINISH_TIMEOUT, cmd="transcribe_files",
                           meeting_dir=str(self.meeting_dir), vocabulary=self.vocabulary)
        self.close()
        if not reply.get("ok"):
            raise LiveError(str(reply.get("error") or "transcription failed"))

    def count(self) -> int:
        return self._count

    def seconds(self) -> float:
        return self._seconds

    def new_speech_seconds(self) -> float:
        return self._speech

    def reset_speech(self) -> None:
        """Local and instant; the worker resets on the next tick, so no
        caller ever waits on the worker for this."""
        self._speech = 0.0
        self._reset_pending = True


def _console_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        candidate = exe.with_name("python.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable


if __name__ == "__main__":
    log.setup()
    sys.exit(worker_main())
