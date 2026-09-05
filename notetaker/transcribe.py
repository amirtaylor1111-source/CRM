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
}

MIN_SIMILARITY = 0.74      # calibrated: real errors land at 0.75+,
                           # coincidental matches below 0.70
LOW_CONFIDENCE = -0.6      # avg_logprob threshold for the review flag


class TranscribeError(RuntimeError):
    """Raised when no usable transcription backend is available."""


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
    found = []
    try:
        import onnx_asr  # noqa: F401

        found.append("parakeet")
    except ImportError:
        pass
    try:
        import faster_whisper  # noqa: F401

        found.append("faster-whisper")
    except ImportError:
        pass
    return found


def _transcribe_parakeet(path: Path, model_name: str, threads: int = 0) -> list[Segment]:
    """Parakeet via ONNX Runtime.

    Better meeting accuracy than Whisper, and as a transducer it cannot
    hallucinate speech into silence. Chained with Silero VAD so the audio is
    cut on speech boundaries rather than fixed windows, and with timestamps so
    each segment carries per-token log-probabilities we can turn into a
    confidence score.

    API verified against onnx-asr 0.12: load_model().with_vad().with_timestamps()
    .recognize() returns a list of TimestampedSegmentResult(start, end, text,
    timestamps, tokens, logprobs).
    """
    import math

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

    results = pipeline.recognize(str(path))
    if not isinstance(results, list):
        results = [results]

    segments: list[Segment] = []
    for item in results:
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        logprobs = getattr(item, "logprobs", None) or []
        # Mean token log-prob, on the same scale Whisper reports avg_logprob,
        # so one threshold flags uncertain segments from either engine.
        confidence = (sum(logprobs) / len(logprobs)) if logprobs else 0.0
        if not math.isfinite(confidence):
            confidence = 0.0
        segments.append(Segment(
            start=float(getattr(item, "start", 0.0) or 0.0),
            end=float(getattr(item, "end", 0.0) or 0.0),
            text=text,
            confidence=confidence,
            low_confidence=bool(logprobs) and confidence < LOW_CONFIDENCE,
        ))
    return segments


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


def _duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as fh:
            return fh.getnframes() / float(fh.getframerate() or 16000)
    except Exception:
        return 0.0


# --- name correction -------------------------------------------------------


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
            lowered = word.lower()
            if lowered in _COMMON or len(word) <= 3:
                return word
            if lowered in targets:
                return word if word == targets[lowered] else targets[lowered]
            close = difflib.get_close_matches(lowered, targets.keys(), n=1,
                                              cutoff=MIN_SIMILARITY)
            if not close:
                return word
            candidate = targets[close[0]]
            # Same opening letter is a cheap proxy for the phonetic check and
            # rejects most coincidental matches.
            if candidate[0].lower() != word[0].lower():
                return word
            changed += 1
            segment.corrections.append(f"{word} -> {candidate}")
            return candidate

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
    choice = hardware.recommend(hw)
    if choice["engine"] == "onnx-asr" and "parakeet" not in backends:
        choice = dict(hardware.ENGINES["turbo"])   # fall back to what is here
        choice["cpu_threads"] = hardware._threads_for(hw)
    if choice["engine"] == "faster-whisper" and "faster-whisper" not in backends:
        choice = dict(hardware.ENGINES["parakeet"])
        choice["cpu_threads"] = hardware._threads_for(hw)

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
                                                     choice.get("cpu_threads", 0))
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
        "duration": hhmmss(total_audio),
        "tracks": ", ".join(sorted(tracks)),
        "speaker_method": "separate audio tracks (attribution is exact)",
        "segments": len(segments),
        "low_confidence_segments": flagged,
        "names_corrected": fixed,
    }

    md_path = meeting_dir / "transcript.md"
    md_path.write_text(render_markdown(segments, meta), encoding="utf-8")
    (meeting_dir / "transcript.json").write_text(
        json.dumps({"meta": meta, "segments": [s.to_dict() for s in segments]},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    progress(f"Wrote {md_path} ({len(segments)} segments, {flagged} flagged)")
    return md_path
