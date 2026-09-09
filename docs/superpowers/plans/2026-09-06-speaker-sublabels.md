# Plan: speaker sub-labels inside system.wav

**6 September 2026. Not implemented. Nothing in this note has been written to
a `.py` file, a test or `CLAUDE.md`, and nothing is committed.**

Another session ("Meeting notetaker CRM setup") has uncommitted widget work in
this tree touching `capture.py`, `cli.py`, `server.py`, `transcribe.py`,
`uistate.py`, `live.py`, `ui/index.html` and four test files. Amir has not
decided whether to commit it. That session asked for the diarization change to
wait for his decision, so this is written as a plan a later session can execute
in one sitting rather than as code.

Precondition already met: the sherpa-onnx spike passed, conditional on
calibration. See `docs/superpowers/spikes/2026-09-06-sherpa-onnx-diarization.md`.

## What this feature is, and what it must never become

`system.wav` can hold more than one remote voice. The two-track design has
nothing to say about which of them is speaking, and that is the only real gap
in the accuracy story. A diarisation model can split that file. It is also
wrong often enough that `docs/accuracy.md` puts free diarisation at roughly one
attribution error in eight, against the roughly 100% the two-track split gets.

So the guess ships as an annotation that sits beside the reliable label and can
never be mistaken for it:

- off by default, on a flag,
- in its own field, never overwriting `speaker`,
- rendered at the end of the line in backticks, lowercase, always ending in a
  question mark, never inside the bold name,
- carrying the existing `⚠` uncertainty marker, in a different position from
  the one that already means "the words are uncertain",
- described in `transcript.json` meta as "model-derived, unreliable".

`meta["speaker_method"]` stays byte-identical:
`separate audio tracks (attribution is exact)`. It describes the authoritative
labels and must not be softened.

Because phone imports write their audio to `system.wav`, this feature also
applies to phone transcripts, where it is most tempting and least reliable: a
phone recording is one mixed channel with both parties in it, which is the
hardest possible input. The `CLAUDE.md` rewrite below says so explicitly.

## Findings from the current working tree that change the plan

Read these before writing code. The tree has moved since the feature was first
sketched.

1. **The suite is 251 tests, not 156.** `HANDOFF.md` says 251 and that is
   current. All must stay green.

2. **`transcribe_meeting` is not the only writer of `transcript.json` any
   more.** Both paths go through `transcribe.write_transcript(meeting_dir,
   segments, meta)` and both build `Segment` objects through
   `transcribe.segment_from_result`. So the schema change belongs on the
   `Segment` dataclass and in `to_dict()` / `render_markdown()`, and it is
   picked up by both paths for free.

3. **The widget's Stop does not call `transcribe_meeting` at all in the normal
   case.** `server.py` `_finish` calls `live.LiveProcess.finish()`, which in the
   worker calls `LiveTranscriber.finish()` and writes the final transcript from
   `LiveTranscriber._write(live=False)`. `transcribe_meeting` is only reached
   when the live pass errored (`transcribe_files`) or from `mtg transcribe`,
   `mtg stop --no-transcribe` plus a later `mtg transcribe`, `app.py`'s classic
   window, and `phone.py`.

   Plumbing `speaker_guess` through `transcribe_meeting` alone would therefore
   leave the widget path, the main path for laptop meetings, with no
   sub-labels. `LiveTranscriber.finish()` needs a diarisation pass of its own.
   That is the right place anyway: it runs after Stop, and the spike measured
   3.3 to 3.9 cores busy, so this can never run during a call.

4. **`LiveTranscriber.resume()` reconstructs `LiveSegment`s field by field**
   from `transcript.json` (start, end, text, speaker, confidence,
   low_confidence, corrections). Any new field must be restored there too or a
   reopened widget silently drops it. It only resumes transcripts whose
   `meta.live` is true, so in practice guesses will not be present, but the
   round trip should still be lossless.

5. **`live.split_at()` and `live.parakeet()` construct `LiveSegment`s by
   keyword.** They do not need to change if the new fields default to `None`
   and `False`, but a segment split at a commit boundary loses nothing only
   because guesses are assigned after the call, never during it.

6. **`phone.import_recording` already takes `title` and `when`.** The signature
   is `import_recording(path, root=None, transcribe=True, progress=..., title=None,
   when=None)` and `store.create_meeting` now accepts `started_at`. `mtg phone`
   already has `--title` and `--when`. Add `--speaker-guess` alongside them and
   thread it through `import_folder` and `import_recording` to the
   `transcribe_meeting` call at `phone.py:219`.

7. **`cmd_stop` and `cmd_transcribe` share `cli._transcribe(meeting_dir)`.**
   Give that helper the parameter and put `--speaker-guess` on both
   subcommands. The brief named `stop` and `phone`; `transcribe` gets it too
   because it is the natural way to add guesses to a meeting that already has a
   transcript, and it costs one line.

8. **`live.LiveProcess._spawn` calls `subprocess.Popen` with no `env=`**, so
   the worker inherits the widget's environment. `MTG_SPEAKER_GUESS=1` reaches
   the worker with no new endpoint and no protocol change. `assistant.clean_env`
   strips only `ANTHROPIC*` and most `CLAUDE*`, so it does not interfere.

9. **`models/sherpa-onnx/` already holds every model file**, downloaded during
   the spike, gitignored twice over by `models/` and `*.onnx`. The
   implementation does not download anything. Note the file on disk is
   `wespeaker_en_voxceleb_CAMPP.onnx`, renamed from the URL's `CAM%2B%2B`.

## Field name and marker

On `transcribe.Segment`, two new attributes:

```python
@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str = ""
    confidence: float = 0.0
    low_confidence: bool = False
    corrections: list[str] = field(default_factory=list)
    speaker_guess: str | None = None            # "S1", "S2", ... or None
    speaker_guess_low_confidence: bool = False
```

`speaker_guess` is `"S1"`, `"S2"` and so on: one-based, derived from the
diarisation cluster index. Never a person's name, never `"Them"`, never a track
name. A reader must not be able to confuse it with the real label, and a name
in this field would feed the habit of quoting it.

`to_dict()` emits both keys **only when `speaker_guess is not None`**, so every
existing transcript, every existing test and every consumer that reads
`transcript.json` is untouched when the feature is off:

```python
    def to_dict(self) -> dict[str, Any]:
        out = {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text,
            "speaker": self.speaker,
            "confidence": round(self.confidence, 3),
            "low_confidence": self.low_confidence,
            "corrections": self.corrections,
        }
        if self.speaker_guess is not None:
            out["speaker_guess"] = self.speaker_guess
            out["speaker_guess_low_confidence"] = self.speaker_guess_low_confidence
        return out
```

**The marker is the existing `⚠`**, U+26A0, reused rather than reinvented, but
in a different position. After the colon it keeps its current meaning, that the
words were uncertain. Inside the backticks it means the guess itself was
uncertain. Two positions, two meanings, no new symbol to learn.

`speaker_guess_low_confidence` is true when either:

- the winning diarisation speaker covers less than **60%** of the ASR segment's
  duration, or
- two or more diarisation speakers overlap the segment at all.

When no turn overlaps the segment, `speaker_guess` stays `None` and nothing is
rendered on that line.

In `meta`, three keys, added only when guesses were actually produced:

```python
"speaker_guess_method": "sherpa-onnx pyannote-segmentation-3.0 + "
                        "nemo_en_titanet_small (model-derived, unreliable)",
"speaker_guess_tracks": "system",
"speaker_guess_speakers": <int>,
```

## Rendering in transcript.md

The line format is unchanged: `[hh:mm:ss] **Speaker:**<flag> text`. The guess
is appended after the text.

```
[00:04:12] **Caller:** ...text... `voice S2?`
[00:04:31] **Caller:** ⚠ ...text... `voice S1?⚠`
```

When any guess is present, one blockquote goes immediately after the existing
machine-authored comment, before the first speaker line:

```
> `voice S1?` tags are a diarisation model's guess, run on system.wav only. They are often wrong and are not the speaker labels. The bold name on each line is the reliable attribution. A ⚠ inside the backticks means even the guess was uncertain.
```

Sketch:

```python
def render_markdown(segments: list[Segment], meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append("<!-- Machine-authored. Do not edit; write notes.md instead. -->")
    if any(s.speaker_guess for s in segments):
        lines.append("")
        lines.append(GUESS_HEADER)
    lines.append("")

    last_speaker = None
    for segment in segments:
        if segment.speaker != last_speaker:
            lines.append("")
            last_speaker = segment.speaker
        flag = " ⚠" if segment.low_confidence else ""
        tail = ""
        if segment.speaker_guess:
            mark = "⚠" if segment.speaker_guess_low_confidence else ""
            tail = f" `voice {segment.speaker_guess}?{mark}`"
        lines.append(
            f"[{hhmmss(segment.start)}] **{segment.speaker}:**{flag} {segment.text}{tail}"
        )
    lines.append("")
    return "\n".join(lines)
```

`GUESS_HEADER` is a module constant holding the blockquote above, on one line.

## The control surface

Off by default, everywhere.

| Entry point | Control |
|---|---|
| `mtg stop` | `--speaker-guess` |
| `mtg transcribe` | `--speaker-guess` |
| `mtg phone` | `--speaker-guess` |
| widget / `server.py` / `app.py` | `MTG_SPEAKER_GUESS=1` |

The env var exists so the UI can turn the feature on without a new endpoint and
without a change to the worker protocol. Read it in exactly one place, a helper
in `diarize.py`, and have the server and the live worker call that helper:

```python
def wanted() -> bool:
    """True when the user asked for sub-labels via the environment."""
    return os.environ.get("MTG_SPEAKER_GUESS", "").strip() in {"1", "true", "yes", "on"}
```

When the flag is on and `diarize.available()` is false, print one line saying
diarisation is not installed and carry on producing a normal transcript. Never
fail the transcription over an optional annotation.

## New module: notetaker/diarize.py

```python
"""Model-derived speaker sub-labels inside a single track.

Everything else in this repo gets speaker attribution from which file the
audio was in. This module is the one exception, and it is deliberately kept
at arm's length: it is optional, off by default, its output is written to a
separate field, and it never touches `Segment.speaker`.

`sherpa_onnx` is imported inside the functions, not at module scope, because
`mtg doctor` has to import this on a machine with no models and no wheels
installed and print a FAIL line rather than a traceback.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import log

_log = log.get("diarize")

SEGMENTATION = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
EMBEDDING = "nemo_en_titanet_small.onnx"

# PROVISIONAL. See "The threshold problem" in
# docs/superpowers/plans/2026-09-06-speaker-sublabels.md. Calibrated on one
# nine-minute phone call, which is not a calibration.
CLUSTER_THRESHOLD = 1.1

MIN_COVERAGE = 0.6          # below this share of the segment, flag the guess


def _threshold() -> float:
    """The clustering threshold, overridable so the regression set can be
    swept without editing code.

    Parsed on call, never at import, and a malformed value falls back to the
    constant. Nothing in this module may raise on import: `mtg doctor` has to
    import it on any machine, and `transcribe_meeting` imports it outside its
    try block, so a typo in an environment variable must never abort a
    transcription over an optional annotation.
    """
    raw = os.environ.get("MTG_DIARIZE_THRESHOLD", "").strip()
    if not raw:
        return CLUSTER_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        _log.warning("MTG_DIARIZE_THRESHOLD=%r is not a number; using %s",
                     raw, CLUSTER_THRESHOLD)
        return CLUSTER_THRESHOLD


def models_dir() -> Path:
    from . import store
    base = os.environ.get("MTG_MODEL_DIR")
    return (Path(base) if base else store.repo_root() / "models") / "sherpa-onnx"


def model_paths() -> tuple[Path, Path]:
    root = models_dir()
    return root / SEGMENTATION, root / EMBEDDING


def available() -> bool:
    """True only if sherpa_onnx imports and both model files are on disk.

    Never raises. A broken wheel, a missing DLL and an absent package all
    mean the same thing here: the feature is not available.
    """
    try:
        import sherpa_onnx        # noqa: F401
    except Exception as exc:      # ImportError, DLL failures, anything
        _log.debug("sherpa_onnx unavailable: %s", exc)
        return False
    try:
        return all(p.exists() for p in model_paths())
    except Exception:
        return False


def wanted() -> bool:
    return os.environ.get("MTG_SPEAKER_GUESS", "").strip() in {"1", "true", "yes", "on"}


def diarize(wav_path, num_speakers: int = -1,
            threshold: float | None = None) -> list[tuple[float, float, int]]:
    """(start, end, speaker_index) turns for one 16 kHz mono WAV.

    `num_speakers=-1` lets clustering decide; a positive value fixes it.
    `threshold=None` resolves through `_threshold()` on every call, so a test
    that monkeypatches the environment or the constant takes effect without a
    fresh process. Binding it as a default argument would freeze it at import.
    """
    import wave

    if threshold is None:
        threshold = _threshold()

    import numpy as np
    import sherpa_onnx

    seg_model, emb_model = model_paths()
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(seg_model)),
            num_threads=_threads()),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(emb_model), num_threads=_threads()),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers, threshold=threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)

    with wave.open(str(wav_path), "rb") as fh:
        if fh.getframerate() != sd.sample_rate:
            raise ValueError(f"{wav_path} is {fh.getframerate()} Hz, "
                             f"the model wants {sd.sample_rate}")
        raw = fh.readframes(fh.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0

    turns = sd.process(samples).sort_by_start_time()
    return [(float(t.start), float(t.end), int(t.speaker)) for t in turns]


def assign_guesses(segments, turns) -> None:
    """Attach a sub-label to each segment, in place. Never touches .speaker."""
    for seg in segments:
        span = max(0.0, float(seg.end) - float(seg.start))
        if span <= 0 or not turns:
            continue
        overlap: dict[int, float] = {}
        for start, end, who in turns:
            shared = min(seg.end, end) - max(seg.start, start)
            if shared > 0:
                overlap[who] = overlap.get(who, 0.0) + shared
        if not overlap:
            continue                       # no turn covers it: leave it None
        who, covered = max(overlap.items(), key=lambda kv: kv[1])
        seg.speaker_guess = f"S{who + 1}"
        seg.speaker_guess_low_confidence = (covered / span < MIN_COVERAGE
                                            or len(overlap) > 1)
```

`_threads()` is one line over `hardware._threads_for(hardware.detect())`,
imported lazily for the same reason everything else here is.

Note the `numpy` import is inside `diarize()` as well. `live.py` guards its
numpy import at module scope precisely so `mtg doctor` can import it; do the
same or better here.

## The functions that change

| File | Function | Change |
|---|---|---|
| `notetaker/diarize.py` | new module | `models_dir`, `model_paths`, `available`, `wanted`, `diarize`, `assign_guesses` |
| `notetaker/transcribe.py` | `Segment` (dataclass) | two new fields, defaulting to `None` and `False` |
| `notetaker/transcribe.py` | `Segment.to_dict` | emit the two keys only when `speaker_guess is not None` |
| `notetaker/transcribe.py` | `render_markdown` | guess suffix on the line, blockquote header when any guess exists |
| `notetaker/transcribe.py` | `transcribe_meeting` | new `speaker_guess: bool = False`; run diarisation on the system track only, before `merge_tracks`; add the three meta keys |
| `notetaker/transcribe.py` | `write_transcript` | no signature change; it is the single choke point both paths already share |
| `notetaker/live.py` | `LiveTranscriber.finish` | after the final `tick` has committed the tail audio and written, if guesses are wanted and available, diarise the finished `system.wav` once, assign to the system track, and write again |
| `notetaker/live.py` | `LiveTranscriber._write` | carry the three meta keys when any segment has a guess |
| `notetaker/live.py` | `LiveTranscriber.resume` | restore `speaker_guess` and `speaker_guess_low_confidence` so the round trip is lossless |
| `notetaker/cli.py` | `_transcribe` | new `speaker_guess: bool = False`, passed through |
| `notetaker/cli.py` | `cmd_stop`, `cmd_transcribe`, `cmd_phone` | pass `args.speaker_guess` |
| `notetaker/cli.py` | `build_parser` | `--speaker-guess` on `stop`, `transcribe`, `phone` |
| `notetaker/cli.py` | `cmd_doctor` | one more check line, wrapped so it can never raise |
| `notetaker/phone.py` | `import_recording`, `import_folder` | new `speaker_guess: bool = False`, passed to `transcribe_meeting` |
| `notetaker/server.py` | the finish path | read `diarize.wanted()`; it reaches the live worker through the inherited environment, so this may be documentation only |
| `notetaker/app.py` | `_finish` | pass `speaker_guess=diarize.wanted()` to `transcribe_meeting` |
| `pyproject.toml` | `[project.optional-dependencies]` | new `diarize = ["sherpa-onnx>=1.13.7"]` |

### transcribe_meeting

```python
def transcribe_meeting(meeting_dir, vocabulary=None, speaker_names=None,
                       progress=print, speaker_guess: bool = False) -> Path:
    ...
    # after per_track is filled, before merge_tracks
    guess_meta: dict[str, Any] = {}
    if speaker_guess and "system" in per_track:
        from . import diarize as dz

        if not dz.available():
            progress("  speaker guessing is not installed; "
                     "transcribing without sub-labels")
        else:
            try:
                progress("  guessing who spoke on system.wav ...")
                turns = dz.diarize(tracks["system"])
                dz.assign_guesses(per_track["system"], turns)
                guess_meta = {
                    "speaker_guess_method": dz.METHOD,
                    "speaker_guess_tracks": "system",
                    "speaker_guess_speakers": len({w for _, _, w in turns}),
                }
            except Exception as exc:            # an annotation must not fail a transcript
                _log.exception("speaker guessing failed")
                progress(f"  speaker guessing failed: {str(exc)[:60]}")

    speakers = {"mic": "Me", "system": "Them"}
    ...
    meta = { ...unchanged..., "live": False }
    meta.update(guess_meta)
```

Order matters. `merge_tracks` iterates the per-track dict and sets `.speaker`;
assigning guesses before it proves by construction that guessing cannot reach
`mic` segments, because only `per_track["system"]` is ever passed to
`assign_guesses`.

### LiveTranscriber.finish

```python
    def finish(self) -> int:
        if self.error:
            raise LiveError(f"live transcription failed during the call: {self.error}")
        self.tick(final=True)           # commits the tail audio, and writes once
        if self.error:
            raise LiveError(f"live transcription failed at the end: {self.error}")
        if self._guess_speakers():      # after the last audio, on the whole segment list
            with self._lock:
                self._write(live=False)  # re-emit, now with the guesses and the meta
        return len(self.segments)
```

The order is the point. `tick(final=True)` is what commits the tail audio into
segments, and it calls `_write(live=False)` itself when `added or final`, so
guessing before it would label only the segments that existed before the last
pass and then write that half-labelled list. Guess after the final tick, on the
complete segment list, and write a second time.

`_guess_speakers` is a small private method returning True when it actually
attached guesses: return False immediately unless `diarize.wanted()` and
`diarize.available()`, take `self._lock`, diarise `self.tracks["system"].path`
if it exists, call `assign_guesses` on that track's segments, stash the meta on
`self` for `_write` to pick up, release the lock, and swallow every exception
into `_log` without touching `self.error`. A failed annotation must not push the
widget onto the fallback path, because that path retranscribes the whole call.
`self._lock` is a plain `threading.Lock` and is not reentrant, so
`_guess_speakers` must not call `_write` while holding it; `finish` takes the
lock again for the second write.

Do not diarise inside `tick()`. The spike measured 558 to 731 CPU seconds per
run against about 175 seconds of wall clock, which is 3.3 to 3.9 cores busy on
a machine with 4 to 6 useful ones. Live transcription costs about a third of a
core. This is a post-Stop job only.

### cmd_doctor

One more check, in the same shape as the others and wrapped so a broken wheel
prints a line rather than a traceback:

```python
    try:
        from . import diarize as dz
        guessing = dz.available()
    except Exception as exc:
        guessing = False
        _log.debug("diarize import failed: %s", exc)
    checks.append(("speaker guessing (optional)", guessing,
                   "pip install -e .[diarize] and put the sherpa-onnx models in "
                   "models/sherpa-onnx  (only needed for --speaker-guess)"))
```

This check failing must not change the doctor's exit code in a way that scares
a user who does not want the feature. Simplest honest option: leave it in the
normal `checks` list and accept that it counts as a failure like `pywebview`
does today; the fix line says it is optional. If that reads badly on a fresh
machine, print it in a separate "optional" block below the totals instead. Pick
one and say which in the commit message.

## The threshold problem

The spike's clearest result is that sherpa-onnx's own default clustering
threshold of 0.5 is wrong for this model on this audio by more than a factor of
two: 19 speakers on a call with two people in it, splitting one man's
continuous pricing argument across speaker ids 3, 4 and 6 mid-paragraph. That
output is worse than no labels, because it invents speaker changes a write-up
would then attribute across sides.

The measured sweep, `num_clusters=-1`, on Discovery-1:

| threshold | speakers | share of speech in the top two clusters |
|---:|---:|---:|
| 0.5 | 19 | 0.683 |
| 0.7 | 15 | 0.795 |
| 0.9 | 8 | 0.848 |
| 1.0 | 5 | 0.906 |
| 1.1 | 3 | 0.998 |
| 1.2 | 2 | 1.000 |
| 1.3 | 1 | 1.000 |

The usable band is 1.1 to 1.2. It is 0.1 wide and has a cliff on each side. It
was found by sweeping one nine-minute phone call, so it is not a calibrated
value.

There is a genuine tension here and the implementing session should resolve it
deliberately rather than by accident. The original brief specified
`diarize(wav_path, num_speakers=-1, threshold=0.5)`, matching sherpa's own
default. Shipping 0.5 at the call site would ship the failure the spike found.
The recommendation in this note is:

- keep `threshold` a parameter, defaulting to `None` and resolved on each call
  through `_threshold()`,
- set the module constant `CLUSTER_THRESHOLD` to a plain literal 1.1,
  commented `PROVISIONAL`, with the reason and a pointer to this note,
- make it overridable by `MTG_DIARIZE_THRESHOLD`, parsed inside `_threshold()`
  and falling back to the constant on a malformed value, so the regression
  sweep needs no code edit and a typo cannot raise out of an import,
- and do not write any accuracy claim anywhere until the regression set exists.

A provisional value behind an off-by-default flag, on lines that end in a
question mark and sit under a blockquote saying the tags are often wrong, is
defensible. A value the spike proved wrong is not.

Optional refinement the spike suggested, out of scope for the first commit
because it needs its own tests: drop clusters holding less than about five
seconds of total speech before assigning, which took 19 clusters to 8 on the
worst configuration without touching the clustering at all.

## Tests, written first

New file `tests/test_diarize.py`, plus additions to `tests/test_transcribe.py`.
Every one of these uses fake turn lists and fake `Segment` objects. **None of
them may require `sherpa_onnx`, a model file, or any audio**, so the suite still
runs on a bare machine, which is the same rule that already governs
`mtg doctor`.

The twelve required cases:

1. `test_track_attribution_unchanged_when_guessing` - with a fake diarizer
   returning turns that span the whole timeline, every `Segment.speaker` is
   still exactly `"Me"` / `"Them"` / `"Caller"` from the track it came from.
   **This is the test that protects the project's core claim. If it ever fails,
   revert the feature rather than adjusting the test.**
2. `test_guess_only_applied_to_system_track` - mic segments have
   `speaker_guess is None` even when the fake turns cover their timeline.
3. `test_no_guess_keys_without_flag` - with the flag off, the string
   `"speaker_guess"` does not appear anywhere in the serialised
   `transcript.json`, and `meta` has no `speaker_guess_method`. Assert on the
   raw text as well as the parsed dict, so a nested occurrence cannot hide.
4. `test_assign_picks_max_overlap` - an ASR segment at 10.0 to 14.0 against
   turns `[(9.0, 11.0, 0), (11.0, 15.0, 1)]` gives `"S2"` (3.0 s against 1.0 s).
5. `test_partial_coverage_is_low_confidence` - two assertions in one case, or
   two cases if clearer: coverage under 60% sets
   `speaker_guess_low_confidence` true, and two overlapping speakers sets it
   true even when the winner's coverage is high.
6. `test_no_overlap_gives_none` - turns that do not touch the segment leave
   `speaker_guess is None`, and the rendered line for it contains no backtick.
7. `test_markdown_guess_cannot_be_read_as_a_label` - the rendered line still
   matches `^\[\d\d:\d\d:\d\d\] \*\*Caller:\*\*`, and `"S1"` never appears
   between `**` and `:**`. Regex the rendered text, do not eyeball it.
8. `test_markdown_header_present_only_with_guesses` - the blockquote appears
   exactly once when any segment has a guess and not at all when none does.
9. `test_speaker_method_meta_unchanged` - `separate audio tracks (attribution
   is exact)` is present and identical in both modes.
10. `test_diarize_imports_without_sherpa` - monkeypatch `sys.modules` so
    `import sherpa_onnx` raises (`sys.modules["sherpa_onnx"] = None` makes the
    import raise `ImportError`; a stub module whose `__getattr__` raises
    `RuntimeError` covers the non-ImportError case the HANDOFF warns about).
    `import notetaker.diarize` still succeeds and `available()` returns `False`
    without raising. Cover the environment too: with `MTG_DIARIZE_THRESHOLD`
    set to `"1,1"`, reimporting the module still succeeds and `_threshold()`
    returns `CLUSTER_THRESHOLD`.
11. `test_doctor_reports_diarization_absent_as_a_line_not_a_traceback` - run
    `cmd_doctor` with diarisation unavailable, capture stdout, assert a line
    mentioning speaker guessing is present and that no traceback text appears.
    Follow whatever fixture `tests/test_console.py` already uses for doctor
    output rather than inventing a new one.
12. `test_missing_models_disable_the_feature` - `sherpa_onnx` importable (a
    stub is enough) but `MTG_MODEL_DIR` pointed at an empty `tmp_path` gives
    `available() is False`.

Three more worth adding, cheap and covering the gaps this note found in the
working tree:

13. `test_live_finish_assigns_guesses_to_system_only` - drive
    `LiveTranscriber` with the existing fake transcriber and a fake diarizer,
    call `finish()`, assert mic segments have no guess and system segments do.
14. `test_resume_round_trips_guess_fields` - write a `transcript.json` with
    `live: true` and guess keys, `resume()`, assert both fields survive.
15. `test_phone_import_passes_the_flag` - `mtg phone --speaker-guess` reaches
    `transcribe_meeting` with `speaker_guess=True`, using the existing
    monkeypatch style in `tests/test_phone.py`.

All 251 existing tests must stay green. Never weaken or delete a test to make
something pass.

## Models and cache path

Already on disk from the spike, in `models/sherpa-onnx/`, gitignored by both
`models/` and `*.onnx`. `git ls-files models/` is empty. The implementation
downloads nothing.

| File | Bytes | Source tag |
|---|---:|---|
| `sherpa-onnx-pyannote-segmentation-3-0/model.onnx` | 5,992,913 | `speaker-segmentation-models` |
| `nemo_en_titanet_small.onnx` | 40,257,283 | `speaker-recongition-models` |
| `nemo_en_titanet_large.onnx` | 101,405,493 | same tag, downloaded, never run |
| `wespeaker_en_voxceleb_CAMPP.onnx` | 29,292,684 | same tag, tried and rejected |

Base URL `https://github.com/k2-fsa/sherpa-onnx/releases/download/<tag>/`. The
embedding tag really is spelled `speaker-recongition-models`; that typo is
upstream's and `speaker-recognition-models` returns 404. `CAM++` appears as
`CAM%2B%2B` in the URL and was saved locally as `CAMPP`.

`wespeaker_en_voxceleb_CAM++` was worse on both counts: 17 clusters at
threshold 0.5, and its fixed-two control collapsed to a 494 s against 9.8 s
split. `nemo_en_titanet_small` is the right default.

Package: `sherpa-onnx==1.13.7`, already installed in the CRM venv. Two wheels
resolve for this interpreter because 1.13.7 splits the native libraries out:
`sherpa_onnx-1.13.7-cp312-cp312-win_amd64.whl` and
`sherpa_onnx_core-1.13.7-py3-none-win_amd64.whl`. It reports bundled
`onnxruntime 1.27.1` on the default CPU provider. It goes in
`[project.optional-dependencies]` as `diarize`, never in base `dependencies`.

## CPU cost, measured

On the Latitude 3440, i5-1345U, no CUDA, `num_threads=4`, over 534.6 s of audio:

- wall clock 167 to 200 s, which is 0.31 to 0.37 times realtime
- CPU 558 to 731 seconds, which is 3.3 to 3.9 cores busy
- peak working set 379 to 493 MB
- deterministic: identical configurations three hours apart in different
  processes produced byte-identical results

Extrapolated, the longest recording in the phone batch, Voice 095 at 1h20m33s,
would take about 27 minutes. Diarisation is roughly three times the wall clock
of the Parakeet pass it annotates, and it cannot share a machine with a live
call.

## Documentation changed in the same commit

### CLAUDE.md

Replace the whole `## Two tracks` section, currently lines 49 to 55, with this
text verbatim:

````markdown
## Two tracks

Audio is recorded as two files, so `mic.wav` is the user and `system.wav` is
everyone else. Speaker labels in the transcript come from that, not from a
diarisation model, so they are reliable even where the words are not.

Segments marked `⚠` were low-confidence. Treat their content as uncertain.

`system.wav` can hold more than one remote voice. Run with `--speaker-guess`
and a diarisation model splits that single file into `voice S1?`, `voice S2?`
and so on: written to `speaker_guess` in `transcript.json`, shown in backticks
at the end of the line in `transcript.md`, off unless you ask for it. Those
are model output and wrong often enough that you must never quote one as
fact. The bold name on each line is still the only reliable attribution and
this feature does not change it. A `⚠` inside the backticks means the guess
itself was uncertain. Phone calls are one mixed track, so their guesses are
the least reliable of all; they do not license attributing lines between
speakers in a phone transcript.
````

### docs/phone-calls.md

Replace the closing `## A note on the second speaker` section with something
that keeps the existing claim first and adds the opt-in as a caveat, not as a
capability. Suggested text:

```markdown
## A note on the second speaker

A phone recording is one mixed track, so both voices share it. The transcript
labels everything as the caller rather than splitting it, because guessing who
spoke would be worse than not claiming to know.

`mtg phone --speaker-guess` will add a diarisation model's opinion at the end
of each line, as `` `voice S1?` `` and `` `voice S2?` ``. It is off by default
and it does not change the speaker labels. On a mixed phone track it is the
least reliable input the model can be given, so treat those tags as a hint
about where the conversation turns and nothing more. They do not license
attributing a line, a number or a commitment to one party rather than the
other. If who said what matters, the answer is to listen to the recording.

Laptop meetings do not have this problem: they record you and the far end to
separate files, which is what makes their speaker attribution exact.
```

### README.md

The `## Two tracks, not one` section at line 131 makes the same promise in
user-facing words. It does not have to change for correctness, since the
feature is off by default, but adding two sentences pointing at the opt-in
keeps README and CLAUDE.md telling the same story. Optional in this commit.

### docs/accuracy.md

**Do not touch.** No accuracy claim for sub-labels exists yet and none may be
written until the regression set has been scored. The existing "roughly one
attribution error in eight" line about free diarisation stays exactly as it is,
and the `~100%` row for speaker attribution stays true because this feature
does not touch `speaker`.

## pyproject.toml

```toml
[project.optional-dependencies]
whisper = ["faster-whisper>=1.0"]   # fallback engine
diarize = ["sherpa-onnx>=1.13.7"]   # optional speaker sub-labels inside system.wav
dev = ["pytest>=8.0"]
```

Nothing moves into base `dependencies`.

## Commit

Explicit `git add` by path. The working tree carries unrelated modified files
and untracked work from other sessions that must not be swept in.

```
notetaker/diarize.py
notetaker/transcribe.py
notetaker/live.py
notetaker/cli.py
notetaker/phone.py
notetaker/app.py
notetaker/server.py        (only if it ends up reading the env var)
tests/test_diarize.py
tests/test_transcribe.py
tests/test_live.py         (if 13 and 14 are added)
tests/test_phone.py        (if 15 is added)
CLAUDE.md
docs/phone-calls.md
pyproject.toml
```

Trailer:

```
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
```

The peer session's uncommitted work overlaps `transcribe.py`, `live.py`,
`cli.py` and `server.py`. Do not start until Amir has decided about it, and
when you do, re-read those four files first: the sketches above were written
against the working tree as of 6 September 2026 and will not apply cleanly to a
different one.

## Still gated. Not in this commit.

Two things wait for a real regression set:

1. **Flipping the default to on.** It stays off until sub-labels have been
   scored against hand-labelled audio.
2. **Any accuracy figure for sub-labels in `docs/accuracy.md`.** No number,
   no range, no "usually right". Nothing measured, nothing claimed.

The regression set, which does not exist yet and cannot exist without Amir:

- Record **two or three short calls through `mtg start` / `mtg stop`**, so
  genuine two-track `system.wav` files exist. Five to ten minutes each is
  enough. At least one should have **two or more remote voices on the far
  end**, because that is the case the feature exists for and nothing has ever
  been run on it.
- Keep the `system.wav` files. `mtg prune` deletes audio from transcribed
  meetings, so set these aside first.
- **Hand-label the turns once**, into a small JSON file of
  `(start, end, who)` next to the audio. Once, not per run.
- Score against them: sweep `MTG_DIARIZE_THRESHOLD`, report cluster count
  against truth and per-second agreement, and pick the value from that, not
  from Discovery-1.
- If the usable band for two-track audio sits somewhere other than 1.1 to 1.2,
  that is the finding and it is cheap to get.

The seven phone recordings in `Downloads/Mobile Devices` are a single-track
smoke test only. They cannot serve as the regression set, and no ground truth
exists for them: nobody names themselves on Discovery-1 and its `meeting.json`
lists no participants, so even "two speakers" is a judgement from reading the
transcript.

## Open item for HANDOFF.md

To be appended when this lands, not before:

```markdown
- Speaker sub-labels inside `system.wav` ship off by default behind
  `--speaker-guess` / `MTG_SPEAKER_GUESS=1`. The clustering threshold is
  provisional: it was picked from a sweep of one nine-minute phone call, and
  the usable band is only 0.1 wide with a cliff on each side. Before the
  default can change, or any accuracy figure can go into `docs/accuracy.md`,
  record two or three short calls through `mtg start` / `mtg stop` so real
  two-track `system.wav` files exist, hand-label the turns once, and score
  against those. At least one of those calls needs two or more voices on the
  far end, which is the case the feature exists for and the case nothing has
  been tested on.
```
