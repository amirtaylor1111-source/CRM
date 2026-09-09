# Plan: measure the ASR accuracy claim on accented English

**9 September 2026. Not run.** A cheap way to replace half of the only
unmeasured claim in this repo. Written down because the dataset was found by
a research session and the finding would otherwise be lost; the measurement
itself is a couple of hours and is not urgent.

## The gap this closes

`notetaker/hardware.py:21` says it plainly:

> Every "wer" below is a published benchmark figure for the model, on the
> corpora the leaderboard uses. None of them has been measured on this
> machine, on a laptop microphone, or on a South African accent, and nothing
> in this repo measures one.

Parakeet is the default over Whisper on 6.3% against 7.44%, both citations.
`docs/accuracy.md` repeats them to the user. Nobody has checked whether the
ordering holds on the accents Amir actually deals with.

## The dataset

`intronhealth/afrispeech-200` on Hugging Face. 200 hours of accented English,
120 African accents across 13 countries, 2,463 speakers, expert transcripts.
Ungated. CC-BY-NC-SA-4.0, which permits internal measurement and forbids
training anything shippable, and measurement is all this is for.

It has **per-accent configs**, which is what makes it useful rather than
merely relevant. Pick the accent, do not average across the continent:

```python
load_dataset("intronhealth/afrispeech-200", "isizulu", split="test",
             streaming=True)
```

**Use one config, and stream it.** The card's frontmatter sizes (86 MB dev,
1.48 GB full) are per-config; the prose says the whole dataset is about
120 GB and takes two hours to pull. On 9 September this machine reached
1.01 GB free because a session ran four PyTorch installs without checking.
`load_dataset(..., "all")` would refill it in one command.

## What it does and does not answer

- **Answers:** does Parakeet still beat Whisper on African-accented English,
  on this CPU. That is the one comparison `hardware.py` makes on borrowed
  numbers.
- **Does not answer:** business vocabulary, Amir's microphone, his room, or
  the remote codec on `system.wav`. The corpus is clinical and general.
- **Does not answer the phone problem.** The audio is 44.1 kHz. Phone imports
  are 8 kHz narrowband, and that degradation is untouched by this.
- The card notes validation transcripts were withheld for a challenge that
  ran February to May 2023. Long over, but confirm the chosen split actually
  carries transcripts before building a harness on it.
- The HF dataset viewer refuses this repo because its loader runs arbitrary
  Python, so there is no preview. You find out by loading.

This does **not** replace the seven `system.wav` files and the Fathom
cross-check. That remains the only ground truth on Amir's real calls, and
those recordings must not be pruned. This is the cheaper, broader half.

## Decide what would change the default before measuring it

Otherwise this produces a number and no decision.

Parakeet winning confirms the status quo and costs nothing to act on.
**Whisper winning on word error does not automatically flip the default**,
because the reason Parakeet is preferred is not only accuracy: a transducer
cannot hallucinate fluent sentences into silence, and Whisper can. For a
record of what people agreed, a fabricated commitment is far worse than a
missed word, and word error rate does not measure that axis at all.

So: only a large and consistent Whisper win, across more than one accent
config, would justify revisiting, and even then the fabrication risk needs
its own check rather than being traded away against a WER delta.

## The numbers are a sort key, not only a claim

Found on 9 September, and it raises the stakes above settling an argument.

`hardware.py` ranks engines by their `wer` values when the preferred model is
absent:

```python
key, spec = min(affordable, key=lambda kv: float(kv[1]["wer"].strip("~%")))
```

So on a machine where Parakeet is not installed, the engine is **selected by
unverified citations**, not merely described by them.

Traced rather than assumed, because the obvious reading is wrong in a way
that matters:

- **`recommend()` does not work this way.** It picks on the RAM budget alone
  and hardcodes Parakeet above 1.5 GB. The default on a healthy machine is
  not chosen by these numbers.
- **`pick_installed()` does.** It is the fallback for a machine missing the
  preferred backend, which is exactly the machine `mtg doctor` exists to
  diagnose. Rare on Amir's laptop, where `onnx-asr` is a base dependency, but
  not never: a partial install lands there.

The path now carries a comment pointing at the disclaimer, and its
user-facing `why` string says the ranking is on published benchmarks rather
than a local measurement. That is honesty, not a fix. The fix is the
measurement below.

## What to compare, measured from the engine table

`hardware.py` already carries every candidate, so this is a config change
rather than new work. `MTG_ENGINE` selects one.

| key | engine | model | disk | published WER |
|---|---|---|---|---|
| `parakeet` | onnx-asr | nemo-parakeet-tdt-0.6b-v3 | 670 MB | 6.3% |
| `distil` | faster-whisper | distil-large-v3.5 | 1500 MB | ~7.5% |
| `turbo` | faster-whisper | large-v3-turbo | 1600 MB | ~7.8% |
| `small` | faster-whisper | small | 500 MB | ~13.8% |
| `base` | faster-whisper | base | 150 MB | ~16.6% |

Compare `parakeet` against `turbo`, and `distil` if there is appetite. The
two small models are there for machines that cannot fit the others and are
not candidates for this laptop.

## Cost, checked rather than estimated

Only `onnx_asr` is installed. Missing on 9 September: `datasets`,
`faster_whisper`, `jiwer`, `soundfile`, `librosa`.

Roughly 1.6 GB for the Whisper weights plus a few hundred MB of Python
packages, against 11.2 GB free after the Temp clean-up. Notably
`faster-whisper` uses CTranslate2 and not torch, so this does not repeat what
filled the disk today. Parakeet's weights are already in `models/`.

Stream the dataset so it never lands on disk. Report per-engine WER with
sample counts, and record which accent config was used, because a single
config is not "African-accented English".

Write the result into `docs/accuracy.md` as a measurement, clearly separated
from the published figures, and correct `hardware.py:21` so it stops saying
nothing here measures one.
