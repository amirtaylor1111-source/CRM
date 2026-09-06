# Spike: sherpa-onnx speaker diarization

**6 September 2026. Verdict: PASS, conditional on calibration.** The runtime
works on this laptop and is three times faster than realtime. Its default
clustering threshold is badly wrong for this audio — 19 speakers on a call
with two people in it — and the setting that gets the answer right was found
by sweeping one file. Nothing ships until that threshold is calibrated
against real two-track audio.

## Why this was run

The notetaker's accuracy claim rests on two-track attribution: `mic.wav` is
the user, `system.wav` is everyone else, so speaker labels are a property of
which file the audio was in rather than a model's guess. That claim has
nothing to say about two remote voices sharing `system.wav`, which is the
one real gap. sherpa-onnx is the only Apache-2.0, fully offline, no-key way
to close it, so the question was whether it runs usefully on this machine at
all, before any of it is designed in.

This is a smoke test on the hardest input available — a single mixed phone
track, both parties in one channel — not a measurement of accuracy. Real
scoring needs hand-labelled `system.wav` files from the laptop recorder.

## What was installed

```
C:/Users/AmirTaylor/Downloads/Projects/CRM/.venv/Scripts/python.exe \
    -m pip install sherpa-onnx==1.13.7
```

Two wheels resolve for this interpreter, not one — 1.13.7 splits the native
libraries into their own package:

```
sherpa_onnx-1.13.7-cp312-cp312-win_amd64.whl
sherpa_onnx_core-1.13.7-py3-none-win_amd64.whl
```

(Confirmed with `pip install --dry-run --ignore-installed --report`; the
install itself reported `Requirement already satisfied`, because an earlier
attempt in the same session had already put it in the venv.) The package
reports `sherpa_onnx 1.13.7` against a bundled `onnxruntime 1.27.1`, running
on the default CPU provider. There is no CUDA on this machine and none was
asked for.

**This is not in `pyproject.toml` and must not be added to the base
`dependencies` list.** Modules have to import on a machine with nothing
installed, because `mtg doctor` runs on exactly that machine. When the
sub-labels work lands it goes under a new `[project.optional-dependencies]`
entry named `diarize`, alongside the existing `whisper` and `dev` entries.

## Models

Cached in `models/sherpa-onnx/`, which `.gitignore` already excludes twice
over (`models/` and `*.onnx`), so nothing here is committed and the
implementation reuses the same files without downloading them again.

| File | Bytes | Source |
|---|---:|---|
| `sherpa-onnx-pyannote-segmentation-3-0.tar.bz2` | 6,958,444 | `releases/download/speaker-segmentation-models/` |
| ↳ `sherpa-onnx-pyannote-segmentation-3-0/model.onnx` | 5,992,913 | extracted; this is the file passed to the config |
| `nemo_en_titanet_small.onnx` | 40,257,283 | `releases/download/speaker-recongition-models/` |
| `nemo_en_titanet_large.onnx` | 101,405,493 | same tag; downloaded, not used below |
| `wespeaker_en_voxceleb_CAM++.onnx` | 29,292,684 | same tag; used for the embedding comparison |

All under `https://github.com/k2-fsa/sherpa-onnx/`. The embedding tag is
spelled `speaker-recongition-models` — that typo is upstream's, and
`speaker-recognition-models` is a 404. `CAM++` is `CAM%2B%2B` in the URL.
All four assets returned HTTP 200 on 6 September 2026. The segmentation
archive also ships `model.int8.onnx` (1,540,506 B), which was not used.

## Audio

Discovery-1, the shortest of the seven phone recordings and the one the ops
backlog is waiting on. Converted with the same flags `phone.to_wav` uses, so
the spike measures what production would feed it:

```
ffmpeg -hide_banner -loglevel error -y \
    -i "C:/Users/AmirTaylor/Downloads/Mobile Devices/Discovery-1.m4a" \
    -ac 1 -ar 16000 -c:a pcm_s16le <scratch>/discovery-1.wav
```

ffmpeg 9.0.1. Result: 17,107,798 bytes, `pcm_s16le`, 16000 Hz, 1 channel,
534.616 s. `sd.sample_rate` was asserted equal to 16000 and is.

It was converted into scratch rather than reusing the meeting's own
`system.wav`. `mtg phone` is idempotent on a content hash, so importing the
file for a spike would have burned the ledger entry the real import needed
and left a junk meeting behind.

## Configuration

```python
sherpa_onnx.OfflineSpeakerDiarizationConfig(
    segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
            model=".../sherpa-onnx-pyannote-segmentation-3-0/model.onnx"),
        num_threads=4),
    embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=".../nemo_en_titanet_small.onnx", num_threads=4),
    clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
    min_duration_on=0.3,
    min_duration_off=0.5,
)
```

Constructor names were checked against the installed package rather than
taken from a snippet. `OfflineSpeakerDiarization` exposes exactly three
things: `process`, `sample_rate` and `set_config`.
`result.sort_by_start_time()` returns a plain list of turns, not a result
object. Samples were read with the stdlib `wave` module into float32 mono in
[-1, 1].

## Results

Every run is the same 534.6 s of audio on the same machine, `num_threads=4`,
timed from before the model is built to after `process` returns. `top2` is
the share of speech in the two largest clusters; `>=5s` counts clusters
holding at least five seconds.

| threshold | num_clusters | speakers | segments | wall s | realtime | CPU s | top2 | >=5s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 | -1 | **19** | 67 | 176.4 | 0.330 | 650 | 0.683 | 9 |
| 0.7 | -1 | 15 | 57 | 174.9 | 0.327 | 657 | 0.795 | 7 |
| 0.9 | -1 | 8 | 54 | 199.9 | 0.374 | 731 | 0.848 | 5 |
| 1.0 | -1 | 5 | 47 | 167.9 | 0.314 | 558 | 0.906 | 3 |
| 1.1 | -1 | **3** | 47 | 190.6 | 0.356 | 626 | 0.998 | 2 |
| 1.2 | -1 | **2** | 46 | 171.3 | 0.320 | 583 | 1.000 | 2 |
| 1.3 | -1 | 1 | 24 | 123.6 | 0.231 | 436 | 1.000 | 1 |
| 1.5 | -1 | 1 | 24 | 134.3 | 0.251 | 440 | 1.000 | 1 |
| 0.5 | **2** (control) | 2 | 46 | 170.8 | 0.319 | 654 | 1.000 | 2 |

Peak working set was 379–493 MB per process (each process ran several
configurations and shares one peak). Runs are deterministic: the
`threshold=0.5` and control results are byte-identical to the same
configurations run three hours earlier in a different process, and
`threshold=1.2` with `num_clusters=-1` produces exactly the same 46 segments
as the fixed-two control.

`wespeaker_en_voxceleb_CAM++` was tried as the alternative embedding and is
worse on both counts: 17 clusters at `threshold=0.5`, and its fixed-two
control collapsed to a 494 s / 9.8 s split, which is one speaker with a
rounding error attached. titanet_small is the right default here.

### Against the four pass criteria

**(a) Runs on this CPU.** Yes. No ONNX Runtime provider error, no crash,
exit 0 every time. Nine configurations completed.

**(b) Under five minutes for 534 s.** Yes, comfortably. 167–200 s, which is
0.31–0.37x realtime. Extrapolated, the longest recording in the batch
(Voice 095, 1h20m33s) would take about 27 minutes.

The CPU cost matters more than the wall clock: 558–731 CPU-seconds per run
against ~175 s wall is 3.3 to 3.9 cores busy on a machine with 4 to 6 useful
ones. Live transcription during a call costs about a third of a core.
Diarization cannot run alongside a call; it is a post-Stop job, and at 0.33x
realtime it is roughly three times the wall clock of the Parakeet pass it
would be annotating (about six minutes per audio hour).

**(c) 2 to 4 speakers with `num_clusters=-1`.** **Fails at the prescribed
threshold of 0.5, which returned 19.** It passes at 1.1 (three clusters,
99.8% of speech in two of them, the third holding 0.93 s) and at 1.2 (two
clusters, identical to the control). The usable band is 1.1 to 1.2 and it
has a cliff on each side: 1.0 gives five, 1.3 collapses everything into one.
sherpa-onnx's default of 0.5 is off by more than a factor of two for this
model on this audio.

**(d) Segment count and turn shape.** Yes, at every threshold. 24 to 67
turns, median turn 2.7 to 3.3 s, longest 58 to 73 s, shortest 0.30 s, and
93.8% of the file is inside a turn. Nothing resembling thousands of
fragments. At `threshold=0.5` the two largest clusters still hold 68% of the
speech, so the over-splitting is a long tail of small clusters: eleven of
the nineteen hold under five seconds each, about 20 s between them.

### The qualitative check

Turn boundaries were laid over the real Parakeet transcript for the same
meeting (`meetings/2026-08-27-discovery-1/transcript.json`), assigning each
transcript segment to the turn its midpoint falls in. This is legibility,
not a score.

At `threshold=1.1` and at the fixed-two control, the result reads as a
genuine two-party negotiation: the Discovery buyer states the uplift bar,
the Aged Ventures side answers, and the handovers land where a reader would
put them. Five of 128 transcript segments fell into gaps between turns.

At `threshold=0.5` it reads as nonsense. One person's continuous answer is
split across four different speaker ids inside a single paragraph — the
buyer's pricing argument alone is attributed to speakers 3, 4 and 6 while he
is still making it. That failure mode is worse than no labels at all: it
invents speaker changes mid-thought, and a write-up built on it would
attribute one side's commitment to the other. The two-track design exists
precisely so that attribution is never a guess, and shipping this default
would put a guess back in.

## What this means for the sub-labels work

Build it, with the threshold treated as the whole problem.

- Diarize **only within `system.wav`**. The mic/system split stays
  authoritative and untouched. This adds a sub-label under "Them"; it never
  overrides which file a voice was in.
- Sub-labels go into `transcript.json` as a distinct, clearly model-derived
  field, carrying the existing low-confidence marker. A reader must be able
  to tell at a glance which part of the attribution is exact and which part
  is a model's opinion.
- **Do not ship 1.1 or 1.2.** They are the answer for one 9-minute phone
  call. The band is 0.1 wide with a cliff on each side, and a threshold
  tuned on a single file is not a calibrated threshold. Record two or three
  short calls through the notetaker, hand-label the turns once, and pick the
  value against those. If the band turns out to sit somewhere else for
  two-track audio, that is the finding, and it is cheap to get.
- Consider requiring at least a floor of speech before a cluster is emitted
  at all. Eleven of the nineteen clusters at the default threshold hold
  under five seconds; dropping those alone takes 19 to 8 without touching
  the clustering.
- `models/sherpa-onnx/` already holds everything needed. The download is not
  part of the implementation.
- The "Two tracks" paragraph in `CLAUDE.md` and "Two tracks, not one" in
  `README.md` both need updating in the same commit as the code, and
  `docs/phone-calls.md` still ends by saying a phone recording labels
  everything as the caller, which stays true unless phone imports get
  sub-labels too.

## What was not tested

Accuracy. There is no ground truth for this file — nobody names themselves
on the call, and the meeting record lists no participants — so "two
speakers" is a judgement from reading the transcript, not a label. The
diarization was never given a two-track `system.wav`, which is the only
input that matters for the real feature, and it was never run on a call with
three or more remote voices, which is the case the feature exists for.
`nemo_en_titanet_large` was downloaded and never run.
