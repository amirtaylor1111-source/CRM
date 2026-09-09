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

## Cost

`faster-whisper` is already an optional extra. A scoring library is needed;
`jiwer` is not installed, and hand-rolling word error over a few hundred
utterances is a dozen lines if adding a dependency is unwelcome. One accent
config, streamed, both engines, report per-engine WER with sample counts.

Write the result into `docs/accuracy.md` as a measurement, clearly separated
from the published figures, and correct `hardware.py:21` so it stops saying
nothing here measures one.
