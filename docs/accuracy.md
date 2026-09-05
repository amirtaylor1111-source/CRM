# How accurate is this, really

## The short answer

Around 92–97% of words, depending mostly on the other person's connection.
Speaker attribution is effectively perfect. Names from your CRM come out
right about 98% of the time.

Nothing reaches 100%. Careful professional human transcriptionists run about
4–5% word error on conversational speech, so the mid-90s is close to the
human ceiling, and no paid service beats it by much.

## Where the errors are

| | Expected accuracy | Why |
|---|---|---|
| Your voice | 94–97% | close microphone, uncompressed, ideal conditions |
| Remote participants | 85–92% | already compressed by the conferencing codec before it reaches you |
| Speaker attribution | ~100% | comes from which track the audio was on, not a model's guess |
| Names in your CRM | ~98% | corrected against your contact list after transcription |

**The remote track sets the floor and nothing local can raise it.** By the
time the far end's audio arrives it has been through their microphone, their
codec, and the network. This is the honest reason perfect transcription is
not on offer from anyone at any price.

## Why the notes are more accurate than the transcript

Claude writes the notes with the participant list, the meeting title, and the
full conversation in front of it. A garbled word in the middle of an
otherwise clear sentence is recoverable from context, in the same way you
recover it when listening to someone on a bad line.

So a 95% transcript reliably produces notes whose decisions and action items
are right. Word-level errors that survive tend to be in filler, not in the
substance.

Segments the model was unsure about are marked `⚠` in the transcript, and the
skill instructs Claude to treat those as uncertain rather than asserting
them.

## Why two tracks beats a meeting bot

A bot that joins your call receives the same compressed stream everyone else
does. Recording locally captures your own voice before any of that happens,
at full quality, and captures the incoming audio at the point it reaches your
machine rather than after another round trip.

Separating the two also removes the hardest problem in meeting transcription.
The best free diarisation models get speaker attribution wrong roughly one
time in eight on real meeting audio. Two tracks make the question moot.

## Model choice

`mtg doctor` picks for your hardware. On any machine with more than about
5 GB of RAM it chooses Parakeet, which scores better on meeting audio than
Whisper large-v3 while running roughly ten times faster on a CPU.

| Model | Word error | 1-hour meeting |
|---|---|---|
| Parakeet TDT 0.6B | 6.3% | 4–8 min |
| Whisper large-v3 | 7.4% | 1–2.5 hours on CPU |
| Whisper small | 13.8% | ~20 min |

Parakeet has a second advantage that matters for a record of what people
agreed. Whisper predicts text from its own previous output, so on silence it
sometimes invents fluent, plausible sentences that were never said. Parakeet
is architecturally incapable of that failure. For meeting notes a missed word
is a nuisance; a fabricated commitment is a serious problem.

Override the choice with `MTG_ENGINE` if you want to trade accuracy for
speed.

## Things this deliberately does not do

**No noise reduction.** It sounds like it should help and it measurably does
not: a 2025 study found denoising degraded transcription accuracy in all
forty configurations tested, by up to 46 percentage points. The rawest
capture is the most accurate one.

**No vocabulary hints to the model.** Whisper's prompt only influences the
first thirty seconds of a recording, and can leak into the output. Names are
corrected afterwards against your contact list instead, which covers the
whole file, is logged in `transcript.json`, and can be reversed.
