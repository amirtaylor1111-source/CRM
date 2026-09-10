"""Turn recorded tracks into a transcript Claude can read.

Two design choices carry most of the accuracy:

* **Each track is transcribed separately.** Speaker attribution then comes
  from which file the audio was in, not from a model's guess, and neither
  side's speech is masked by the other's.
* **Names are corrected after the fact, not hinted beforehand.** Whisper's
  prompt only survives the first thirty seconds of a recording, whereas a
  fuzzy match against the CRM's contact list applies to the whole file, is
  logged, and can be undone.

Denoising is deliberately absent. It degraded accuracy in every one of the
forty configurations tested in the literature; the cleanest input is the raw
capture.
"""

from __future__ import annotations

import contextlib
import os
import time
import difflib
import json
import re
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import hardware, log

_log = log.get("transcribe")
from .schema import utcnow

# Words common enough that a near-match to a contact name is more likely a
# coincidence than a mis-transcription. Guards the corrector against turning
# "and" into "Anand".
_COMMON = {
    # The corrector's main guard. A near-match between an ordinary English
    # word and a contact name is almost always coincidence, and rewriting
    # correct text is worse than leaving a name misspelled.
    "about", "above", "after", "again", "against", "all", "almost", "already",
    "also", "although", "always", "and", "another", "any", "anything", "are",
    "around", "back", "because", "been", "before", "being", "best", "better",
    "between", "both", "bring", "business", "but", "call", "called", "can",
    "care", "case", "change", "check", "clear", "come", "coming", "could",
    "course", "customer", "day", "days", "deal", "did", "different", "does",
    "doing", "done", "down", "each", "early", "end", "enough", "even", "ever",
    "every", "exactly", "example", "far", "feel", "few", "find", "first",
    "for", "from", "get", "getting", "give", "going", "good", "got", "great",
    "group", "had", "half", "happen", "happy", "hard", "has", "have", "having",
    "hear", "help", "her", "here", "high", "him", "his", "hold", "hope",
    "how", "however", "idea", "into", "issue", "just", "keep", "kind", "know",
    "large", "last", "late", "later", "least", "leave", "less", "let", "like",
    "line", "little", "long", "look", "looking", "lot", "made", "make",
    "making", "many", "market", "material", "matter", "may", "maybe", "mean",
    "meeting", "might", "mind", "minute", "monday", "money", "month", "more",
    "most", "move", "much", "must", "need", "never", "new", "next", "nice",
    "not", "note", "nothing", "now", "number", "off", "offer", "office",
    "often", "old", "once", "one", "only", "open", "order", "other", "our",
    "out", "over", "own", "part", "people", "perhaps", "place", "plan",
    "please", "point", "possible", "price", "probably", "problem", "process",
    "product", "project", "put", "question", "quite", "rather", "reach",
    "read", "ready", "real", "really", "reason", "right", "run", "said",
    "same", "saw", "say", "saying", "sean", "see", "seem", "send", "sense",
    "set", "share", "she", "short", "should", "show", "side", "since", "small",
    "some", "something", "soon", "sorry", "sort", "sound", "speak", "spend",
    "start", "state", "stay", "still", "stuff", "such", "sure", "table",
    "take", "taking", "talk", "team", "tell", "term", "than", "thank", "that",
    "the", "their", "them", "then", "there", "these", "they", "thing", "think",
    "this", "those", "though", "thought", "three", "through", "time", "today",
    "together", "told", "too", "took", "top", "total", "toward", "try",
    "trying", "turn", "two", "under", "until", "use", "used", "using",
    "value", "very", "want", "was", "way", "week", "well", "went", "were",
    "what", "when", "where", "whether", "which", "while", "who", "why",
    "will", "with", "within", "without", "work", "working", "would", "write",
    "year", "yes", "yeah", "yet", "you", "your",
    # Words this corrector was caught rewriting into contact names.
    "able", "cellar", "cost", "costs", "door", "drop", "firms", "firstly",
    "francs", "frank", "hour", "land", "monthly", "mount", "pull", "race",
    "rape", "rate", "rely", "seen", "sent", "volume",
    # Companies whose names are ordinary English words. Without these, an
    # exact match capitalises the ordinary word: "a capital idea" became
    # "a Capital idea" because a contact works at Capital Legacy. "forex" and
    # "horn" arrived the same way, from Future Forex and Sean Horn, and were
    # caught only once case changes started being logged: "business forex"
    # became "business Forex" in a client transcript.
    "capital", "cell", "cotton", "cross", "discovery", "forex", "future",
    "horn", "legacy", "orion",
}

MIN_SIMILARITY = 0.74      # calibrated: real errors land at 0.75+,
                           # coincidental matches below 0.70
LOWERCASE_SIMILARITY = 0.92
# The model capitalises what it heard as a name, so a lowercase word is one
# it heard as an ordinary word, and rewriting those is where this went wrong:
# across seven real meetings it made 106 substitutions, and 97 of them were
# lowercase words at exactly this kind of distance. "able" became a contact
# called Alex thirteen times, "costs" became Cross ten times, "seen" became
# Sean, "hour" became Horn, "rate" became Rael. A lowercase word therefore
# has to be near enough to be a spelling of the name ("kubernets") rather
# than merely similar to it.
LOW_CONFIDENCE = -0.6      # avg_logprob threshold for the review flag


class TranscribeError(RuntimeError):
    """Raised when no usable transcription backend is available."""


class AlreadyTranscribing(TranscribeError):
    """Raised when another process is already transcribing this meeting.

    Marking the work and proceeding anyway was not enough. On 10 September two
    transcriptions of the same meeting ran side by side, each loading its own
    copy of the model, on a laptop with half a gigabyte free. They did not
    fail; they simply took several times longer while swapping against each
    other. Refusing is the only thing that actually prevents it.
    """


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str = ""
    confidence: float = 0.0
    low_confidence: bool = False
    corrections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text,
            "speaker": self.speaker,
            "confidence": round(self.confidence, 3),
            "low_confidence": self.low_confidence,
            "corrections": self.corrections,
        }


def hhmmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


# --- backends --------------------------------------------------------------


def available_backends() -> list[str]:
    """Engines that import cleanly. Anything else counts as absent."""
    found = []
    for module, name in (("onnx_asr", "parakeet"), ("faster_whisper", "faster-whisper")):
        try:
            __import__(module)
            found.append(name)
        except Exception as exc:           # ImportError, DLL failures, anything
            _log.debug("backend %s unavailable: %s", module, exc)
    return found


def _transcribe_parakeet(path: Path, model_name: str, threads: int = 0,
                         progress=print) -> list[Segment]:
    """Parakeet via ONNX Runtime.

    Better meeting accuracy than Whisper, and as a transducer it cannot
    hallucinate speech into silence. Chained with Silero VAD so the audio is
    cut on speech boundaries rather than fixed windows, and with timestamps so
    each segment carries per-token log-probabilities we can turn into a
    confidence score.

    API verified by running onnx-asr 0.12 on Windows: for a single file,
    load_model().with_vad().with_timestamps().recognize() returns a
    *generator* of TimestampedSegmentResult(start, end, text, timestamps,
    tokens, logprobs), not a list. Wrapping that generator in a list, as an
    earlier version did, produced a transcript with zero segments from a
    perfectly good recording.
    """
    import onnx_asr

    sess_options = None
    if threads:
        import onnxruntime as ort

        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = threads

    model = onnx_asr.load_model(model_name, quantization="int8",
                                sess_options=sess_options)
    vad = onnx_asr.load_vad("silero")
    pipeline = model.with_vad(vad).with_timestamps()

    def decode(window: Path) -> list[Segment]:
        results = pipeline.recognize(str(window))
        if hasattr(results, "text"):
            results = [results]      # an un-segmented adapter: one result
        else:
            results = list(results)  # the VAD adapter's generator, or a list
        out: list[Segment] = []
        for item in results:
            seg = segment_from_result(item)
            if seg is not None:
                out.append(seg)
        return out

    # The model is loaded once, above, and reused for every window. Only the
    # window's audio and its results are in memory at a time.
    segments = _decode_in_chunks(path, decode, progress)
    return segments


def segment_from_result(item) -> Segment | None:
    """A Segment from one onnx-asr result, or None when it carries no text.

    Shared with the live transcriber so both paths score confidence the same
    way: the mean token log-probability, on the scale Whisper reports
    avg_logprob, so one threshold flags uncertain segments from any engine.
    """
    import math

    text = (getattr(item, "text", "") or "").strip()
    if not text:
        return None
    logprobs = getattr(item, "logprobs", None) or []
    confidence = (sum(logprobs) / len(logprobs)) if logprobs else 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    return Segment(
        start=float(getattr(item, "start", 0.0) or 0.0),
        end=float(getattr(item, "end", 0.0) or 0.0),
        text=text,
        confidence=confidence,
        low_confidence=bool(logprobs) and confidence < LOW_CONFIDENCE,
    )


def _transcribe_whisper(path: Path, model_name: str, threads: int,
                        hotwords: str = "") -> list[Segment]:
    """faster-whisper, tuned against its documented hallucination modes.

    condition_on_previous_text is off: it is the single most effective guard
    against the repetition loops Whisper falls into, at the cost of the
    initial prompt, which the post-hoc corrector replaces anyway.
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=threads)
    raw, _info = model.transcribe(
        str(path),
        beam_size=5,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],   # keep the fallback ladder
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        condition_on_previous_text=False,
        word_timestamps=True,
        hallucination_silence_threshold=2.0,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.5,
            "min_speech_duration_ms": 250,
            "max_speech_duration_s": 25,
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 200,
        },
        repetition_penalty=1.05,
        hotwords=hotwords or None,
    )

    segments = []
    for item in raw:
        text = (item.text or "").strip()
        if not text:
            continue
        confidence = float(getattr(item, "avg_logprob", 0.0) or 0.0)
        segments.append(
            Segment(
                start=float(item.start),
                end=float(item.end),
                text=text,
                confidence=confidence,
                low_confidence=confidence < LOW_CONFIDENCE
                or float(getattr(item, "no_speech_prob", 0.0) or 0.0) > 0.6,
            )
        )
    return segments


# --- chunked, resumable decoding -------------------------------------------
#
# A 62-minute track used to be decoded in one call, with every segment held in
# memory and nothing written until the end. On 10 September that killed two
# transcriptions of a real meeting on a laptop with 1.6 GB free: the process
# vanished with no exception and no log line, and an hour of work was lost
# each time because nothing had been written yet.
#
# Decoding a window at a time fixes both halves. Peak memory is one window
# rather than one meeting, and every finished window is on disk, so a process
# that dies resumes instead of starting over.

CHUNK_SECONDS = 300.0          # five minutes: ~12 windows an hour, per track
CHECKPOINT_SUFFIX = ".partial.jsonl"


def _checkpoint_path(track: Path) -> Path:
    return track.with_suffix(track.suffix + CHECKPOINT_SUFFIX)


def _load_checkpoint(path: Path) -> tuple[list[Segment], float]:
    """Segments already decoded, and the point to resume from."""
    segments: list[Segment] = []
    done_to = 0.0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return segments, done_to
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            break               # a half-written last line; stop, do not guess
        if row.get("_chunk_end") is not None:
            done_to = max(done_to, float(row["_chunk_end"]))
            continue
        segments.append(Segment(
            start=float(row["start"]), end=float(row["end"]), text=row["text"],
            speaker=row.get("speaker", ""), confidence=float(row.get("confidence") or 0.0),
            low_confidence=bool(row.get("low_confidence")),
            corrections=list(row.get("corrections") or [])))
    return segments, done_to


def _append_checkpoint(path: Path, rows: list[dict]) -> None:
    """Append and flush, so a kill loses at most the window in progress."""
    try:
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False))
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        _log.warning("could not checkpoint %s", path, exc_info=True)


def _write_chunk(source: Path, destination: Path, start: float, length: float) -> float:
    """Copy a window of a wav into its own file. Returns its real length."""
    with wave.open(str(source), "rb") as src:
        rate = src.getframerate() or 16000
        src.setpos(min(int(start * rate), src.getnframes()))
        frames = src.readframes(int(length * rate))
        with wave.open(str(destination), "wb") as dst:
            dst.setnchannels(src.getnchannels())
            dst.setsampwidth(src.getsampwidth())
            dst.setframerate(rate)
            dst.writeframes(frames)
    return len(frames) / float(rate * max(1, src.getsampwidth()) * max(1, src.getnchannels()))


def _decode_in_chunks(path: Path, decode, progress) -> list[Segment]:
    """Decode a track window by window, resuming from any checkpoint.

    `decode` takes a wav path and returns segments with times relative to it.
    """
    checkpoint = _checkpoint_path(path)
    segments, done_to = _load_checkpoint(checkpoint)
    total = _duration(path)
    if segments or done_to:
        progress(f"    resuming at {hhmmss(done_to)} of {hhmmss(total)}"
                 f" ({len(segments)} segment(s) already decoded)")
        _log.info("resuming %s at %.0fs with %d segments", path.name, done_to, len(segments))

    window = path.with_suffix(path.suffix + ".chunk.wav")
    offset = done_to
    while offset < total - 0.05:
        length = min(CHUNK_SECONDS, total - offset)
        try:
            _write_chunk(path, window, offset, length)
            found = decode(window)
        finally:
            try:
                window.unlink()
            except OSError:
                pass
        rows = []
        for seg in found:
            seg.start += offset
            seg.end += offset
            segments.append(seg)
            rows.append(seg.to_dict())
        offset += length
        rows.append({"_chunk_end": offset})
        _append_checkpoint(checkpoint, rows)
        progress(f"    {hhmmss(offset)} / {hhmmss(total)}")
    return segments


def _duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as fh:
            return fh.getnframes() / float(fh.getframerate() or 16000)
    except Exception:
        return 0.0


# --- name correction -------------------------------------------------------


def speaker_method(segments: Iterable[Segment], tracks: Iterable[str]) -> str:
    """How attribution was decided, said honestly for what was captured.

    The two-track split is exact: audio in the mic file is the user and audio
    in the system file is everyone else. That stays true even when a track
    holds nothing, and a track holding nothing is exactly what happens when
    the user is on speakers rather than headphones, or their microphone is
    muted: both sides then land on one track under one label. Claiming
    exactness without saying so reads as a guarantee that both speakers were
    separated, which in that case they were not.
    """
    exact = "separate audio tracks (attribution is exact)"
    if len(list(tracks)) < 2:
        return exact
    spoken: dict[str, float] = {}
    for segment in segments:
        if segment.text.strip():
            spoken[segment.speaker] = spoken.get(segment.speaker, 0.0) + (
                segment.end - segment.start)
    total = sum(spoken.values())
    if not total:
        return exact
    # A stray "Yeah." on an otherwise empty track is not that speaker taking
    # part; it is bleed, or the one word loud enough to reach a muted
    # microphone. A real drive produced two such segments, 1.2 seconds
    # against 202, and a test for literal silence would have passed it.
    quiet = [label for label in ("Me", "Them")
             if spoken.get(label, 0.0) / total < 0.02]
    if not quiet:
        return exact
    which = " and ".join(quiet)
    return (f"{exact}; almost no speech on the {which} track, so both sides may "
            f"be under one label")


def correct_names(segments: Iterable[Segment], vocabulary: list[str]) -> int:
    """Repair mis-transcribed proper nouns against the CRM's known names.

    Conservative on purpose. A substitution requires a strong similarity, a
    matching first letter, and a token that is not an ordinary English word,
    because silently rewriting correct text is worse than leaving a name
    misspelled. Every change is recorded on the segment.
    """
    if not vocabulary:
        return 0

    # Index single-word forms; multi-word names are handled by their parts.
    targets = {}
    for term in vocabulary:
        for part in term.split():
            if len(part) > 3:
                targets.setdefault(part.lower(), part)

    if not targets:
        return 0

    changed = 0
    for segment in segments:
        def replace(match: re.Match) -> str:
            nonlocal changed
            word = match.group(0)
            # A possessive is the name plus an ending. Compare the name and
            # put the ending back, or "Salvador's Quest" loses its apostrophe
            # and becomes "Salvador Quest".
            ending = ""
            if len(word) > 3 and word[-2:].lower() == "'s":
                word, ending = word[:-2], word[-2:]
            lowered = word.lower()
            if lowered in _COMMON or len(word) <= 3:
                return word + ending
            if lowered in targets:
                fixed = targets[lowered]
                if fixed == word:
                    return word + ending
                # Spelt right, cased wrong. Still a change to what was said,
                # so it belongs in the log with every other one.
                changed += 1
                segment.corrections.append(f"{word}{ending} -> {fixed}{ending}")
                return fixed + ending
            cutoff = MIN_SIMILARITY if word[:1].isupper() else LOWERCASE_SIMILARITY
            close = difflib.get_close_matches(lowered, targets.keys(), n=1,
                                              cutoff=cutoff)
            if not close:
                return word + ending
            candidate = targets[close[0]]
            # Same opening letter is a cheap proxy for the phonetic check and
            # rejects most coincidental matches.
            if candidate[0].lower() != word[0].lower():
                return word + ending
            changed += 1
            segment.corrections.append(f"{word}{ending} -> {candidate}{ending}")
            return candidate + ending

        segment.text = re.sub(r"\b[A-Za-z][A-Za-z'-]+\b", replace, segment.text)
    return changed


# --- merge and render ------------------------------------------------------


def merge_tracks(per_track: dict[str, list[Segment]], speakers: dict[str, str]) -> list[Segment]:
    """Interleave the tracks chronologically, labelling by origin."""
    merged: list[Segment] = []
    for track, segments in per_track.items():
        label = speakers.get(track, track)
        for segment in segments:
            segment.speaker = label
            merged.append(segment)
    merged.sort(key=lambda s: (s.start, s.speaker))
    return merged


def render_markdown(segments: list[Segment], meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append("<!-- Machine-authored. Do not edit; write notes.md instead. -->")
    lines.append("")

    last_speaker = None
    for segment in segments:
        if segment.speaker != last_speaker:
            lines.append("")
            last_speaker = segment.speaker
        flag = " ⚠" if segment.low_confidence else ""
        lines.append(f"[{hhmmss(segment.start)}] **{segment.speaker}:**{flag} {segment.text}")
    lines.append("")
    return "\n".join(lines)


def transcribe_meeting(
    meeting_dir: Path,
    vocabulary: list[str] | None = None,
    speaker_names: dict[str, str] | None = None,
    progress=print,
) -> Path:
    """Transcribe every track in a meeting and write transcript.md/.json."""
    meeting_dir = Path(meeting_dir)
    if is_being_transcribed(meeting_dir):
        raise AlreadyTranscribing(
            f"{meeting_dir.name} is already being transcribed by another "
            f"process (see {WORKING_FILE}).\n"
            "  Wait for it, or delete that file if you are sure it is stale."
        )
    with _working(meeting_dir):
        return _transcribe_meeting(meeting_dir, vocabulary, speaker_names, progress)


#: Written while a transcription is running and removed when it ends, so a
#: second one can tell a meeting being worked on from an abandoned one. Both
#: the CLI and the widget's worker come through transcribe_meeting, so one
#: marker here covers both.
WORKING_FILE = "transcribing.lock"

#: A marker older than this is from a process that died. An hour of audio
#: takes minutes, so this is generous by an order of magnitude.
WORKING_STALE_SECONDS = 3600.0


def is_being_transcribed(meeting_dir: Path) -> bool:
    marker = Path(meeting_dir) / WORKING_FILE
    try:
        return time.time() - marker.stat().st_mtime < WORKING_STALE_SECONDS
    except OSError:
        return False


@contextlib.contextmanager
def _working(meeting_dir: Path):
    marker = meeting_dir / WORKING_FILE
    try:
        marker.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass                       # a marker we cannot write must not stop the work
    try:
        yield
    finally:
        try:
            marker.unlink()
        except OSError:
            pass


def _transcribe_meeting(
    meeting_dir: Path,
    vocabulary: list[str] | None = None,
    speaker_names: dict[str, str] | None = None,
    progress=print,
) -> Path:
    tracks = {name: meeting_dir / f"{name}.wav"
              for name in ("mic", "system")
              if (meeting_dir / f"{name}.wav").exists()}
    if not tracks:
        raise TranscribeError(
            f"No audio found in {meeting_dir}.\n"
            "  Expected mic.wav or system.wav — was the meeting recorded?"
        )

    backends = available_backends()
    if not backends:
        raise TranscribeError(
            "No transcription engine is installed.\n"
            "  Fix:  pip install onnx-asr[cpu,hub]\n"
            "  Or rerun setup-windows.ps1."
        )

    hw = hardware.detect()
    choice = hardware.pick_installed(backends, hw)

    total_audio = sum(_duration(p) for p in tracks.values())
    _log.info("engine=%s model=%s tracks=%s audio=%s", choice["engine"], choice["model"],
              sorted(tracks), hhmmss(total_audio))
    progress(f"Transcribing {len(tracks)} track(s), {hhmmss(total_audio)} of audio")
    progress(f"Engine: {choice['model']} ({choice['engine']}) — "
             f"{hardware.format_estimate(total_audio, choice, hw)}")

    hotwords = ", ".join((vocabulary or [])[:20])
    per_track: dict[str, list[Segment]] = {}
    for name, path in tracks.items():
        progress(f"  {name}.wav ...")
        if choice["engine"] == "onnx-asr":
            per_track[name] = _transcribe_parakeet(path, choice["model"],
                                                   choice.get("cpu_threads", 0),
                                                   progress=progress)
        else:
            per_track[name] = _transcribe_whisper(
                path, choice["model"], choice["cpu_threads"], hotwords
            )

    speakers = {"mic": "Me", "system": "Them"}
    speakers.update(speaker_names or {})
    segments = merge_tracks(per_track, speakers)

    fixed = correct_names(segments, vocabulary or [])
    if fixed:
        progress(f"  corrected {fixed} name(s) against the CRM")

    flagged = sum(1 for s in segments if s.low_confidence)
    meta = {
        "generated_at": utcnow(),
        "engine": choice["engine"],
        "model": choice["model"],
        "expected_accuracy": choice.get("wer", "unknown"),
        # The meeting is as long as its longest track, not as long as its
        # tracks added together. A 39-minute two-track call reported
        # 01:17:32 on 10 September, which is the machine's workload and
        # not a fact about the meeting.
        "duration": hhmmss(max(_duration(q) for q in tracks.values())
                           if tracks else 0.0),
        "tracks": ", ".join(sorted(tracks)),
        "speaker_method": speaker_method(segments, tracks),
        "segments": len(segments),
        "low_confidence_segments": flagged,
        "names_corrected": fixed,
        "live": False,
    }

    md_path = write_transcript(meeting_dir, segments, meta)
    # Only now, with the transcript safely written, are the checkpoints
    # redundant. Removing them earlier would mean a crash between the last
    # window and the write costs the whole meeting again.
    for track in tracks.values():
        for leftover in (_checkpoint_path(track),
                         track.with_suffix(track.suffix + ".chunk.wav")):
            try:
                leftover.unlink()
            except OSError:
                pass
    progress(f"Wrote {md_path} ({len(segments)} segments, {flagged} flagged)")
    return md_path


def write_transcript(meeting_dir: Path, segments: list[Segment], meta: dict[str, Any]) -> Path:
    """Write transcript.md and transcript.json; returns the markdown path.

    Atomic, because the live transcriber rewrites these every half minute
    while a headless Claude may be reading them for a brief.
    """
    from .store import _write_atomic

    meeting_dir = Path(meeting_dir)
    md_path = meeting_dir / "transcript.md"
    _write_atomic(md_path, render_markdown(segments, meta))
    _write_atomic(meeting_dir / "transcript.json",
                  json.dumps({"meta": meta, "segments": [s.to_dict() for s in segments]},
                             indent=2, ensure_ascii=False))
    return md_path
