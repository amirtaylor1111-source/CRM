# Semantic search over the corpus: measured, and not yet

**9 September 2026. Not built, deliberately.** A tooling-research session
proposed embeddings and a reranker over the meeting corpus. Three sessions
reached "do not build" independently, by three different routes. This note
exists so the next session finds the reasoning instead of re-deriving the
design, and so the good parts of the research are not lost with the verdict.

The first argument below is the one that stays true however large the corpus
gets. Everything after it is a matter of size, and size changes.

## 1. Embedding errors are silent. Grep errors are loud.

At 3 to 8 percent word error, this decides transcript retrieval on its own.

A real line from this repo's transcripts, before the corrector was fixed:
"recalibrate your pricing to an Horn". The word was "hour".

Grep for "hour" returns nothing. **You know you missed**, so you widen the
search, try another word, open the file. The failure is visible and it
prompts the correct next action.

An embedding search returns *something*. The nearest neighbour in a space
that the wrong word has already moved the chunk within, and nothing in the
result distinguishes a good hit from a confidently wrong one. The failure is
invisible, and it arrives dressed as an answer.

In a corpus where roughly one word in twenty is wrong, a method that fails
visibly beats one that fails silently. This is the same argument the Hub
export accepted on the same day for what it ingests, and it applies *harder*
to retrieval than to storage: storage merely holds a wrong word, retrieval
turns it into an answer.

## 2. The whole corpus fits in a prompt, so there is nothing to retrieve from

Measured on the real repo, 26 meetings, at roughly four bytes per token.

| | Size | Tokens |
|---|---|---|
| Every `notes.md` in the corpus | 64 KB | ~16k |
| Every transcript in the corpus | 369 KB | ~94k |
| Largest single transcript | 102 KB | ~26k |
| Largest single `notes.md` | 12 KB | ~3k |
| `/prep`, heaviest contact, notes only | | ~2k |
| `/prep`, heaviest contact, notes and transcripts | | ~21k |

No query this system can be asked fails to fit in context. `/ask` is scoped
to one meeting and the largest is 26k tokens. `/prep` on the heaviest contact
is 2k tokens of notes. Even every transcript ever recorded, concatenated, is
94k.

Retrieval would therefore select a subset of something that could be passed
whole. It cannot improve recall, because nothing is being dropped for want of
room. It can only add a way to drop the right part.

**And the notes-side corpus is smaller still: 8 of the 26 meetings have a
non-empty `notes.md`.** Semantic search across eight documents is a for loop
with extra steps.

## 3. The real `/prep` question is a filter, not a search

"What do I know about this person, on this project, since when" is
`WHERE participant = ?` against fields that are already structured in
`meeting.json`.

Cosine similarity is actively worse at it. It will rank a semantically
similar meeting with the *wrong person* above an exact match with the right
one, which is the one mistake `/prep` must never make.

## 4. Chunk size fights the deep-link that was selling it

`bge-small-en-v1.5` takes about 512 tokens. Transcript segments are a few
seconds of speech each, so chunks are either too thin to embed usefully or
they are grouped. Once grouped, `start_ms` points at the start of a group
rather than at the moment, so the deep-link into the audio gets blurry
exactly when you group enough to make the embeddings work. The feature and
its headline benefit are in tension.

## 5. It bolts a cache onto the least stable component in the repo

The name corrector stabilised on 6 September after four consecutive bugs and
106 false substitutions, all of which were fixed by regenerating transcripts
from audio rather than editing them.

Every corrective run silently makes some fraction of the vectors describe
text that no longer exists, with nothing reporting the drift. Cache
invalidation, attached to the part of the system most likely to change under
you.

## 6. The cost that would have been invisible

`/live-brief` runs every couple of minutes of speech, and each run already
spawns a Claude process on Amir's subscription. Retrieval in the prompt
builder adds retrieved chunks to every one of those prompts, on every call,
permanently, to select from a corpus that fits anyway. It also needs the
*query* embedded, so every brief becomes a forward pass on a 15W CPU already
running Parakeet across two audio streams.

The question dissolves rather than needing an answer: pass the notes whole
and there is no retrieval on the hot path at all.

## The subtle error worth not repeating

The research argued that 900 chunks is past the point where grep works, and
that is true. Grep misses a transcript that says "the water's really hard
round here" when the question is about water hardness.

But "grep is insufficient" and "a vector index is necessary" are different
claims. At this size the fix is to hand the model the text and let it do the
semantic matching, which is the thing it is best at. Building a second
semantic system in front of the first buys nothing until the text stops
fitting.

## What would change the answer: one trigger

**When a single query stops fitting the context window.** Either one
contact's whole meeting history, for `/prep`, or one meeting's transcript,
for `/ask`. On today's numbers the heaviest meeting contributes about 18k
tokens of transcript, so roughly ten recorded meetings with one person.

Not close. Re-run the measurement rather than trusting the table above: sum
`notes.md` and `transcript.md` sizes per meeting, group by participant,
divide by four.

**A whole-corpus trigger was proposed and withdrawn, and it is recorded here
so it is not re-proposed.** The suggestion was to revisit once aggregate
notes exceeded roughly 60k tokens, about 150 meetings with write-ups against
8 today. It is the wrong measure, because nothing in this system ever needs
the whole corpus, only a slice of it: `/prep` needs one person, `/ask` needs
one meeting. That trigger would have fired while every real query still fit
comfortably, and sent some future session down this road years early, which
is precisely the failure this note exists to prevent. A second, looser
trigger beside the binding one is worse than no trigger at all, because it
is the one that fires.

Note that argument 1 is not on this list. Size does not fix it, which is why
it is first.

## If it is ever built, four conditions

1. **Keep it off `/live-brief` entirely.** See 6.
2. **Embed notes and contact files, not transcripts.** Notes are the artifact
   where transcription errors have already been repaired in context, and they
   are a fifth of the volume. Same decision as
   `specs/2026-09-09-meetings-to-hub.md`, same reason. If transcripts are ever
   embedded, the low-confidence flag must travel with every chunk as a
   structural property and never a convention.
3. **A test that fails when a chunk's source text no longer hashes to what
   was embedded.** The `revision` machinery built for the Hub export on the
   same day makes this cheap, and it is the difference between an index that
   is stale and one that is silently wrong.
4. **Retrieval belongs in the Python prompt builder, not in a tool Claude
   calls.** Headless runs have Read, Glob, Grep and Skill only, and a SQLite
   table of float vectors is readable by none of them, so the three surfaces
   that motivate the feature are exactly the three that could not query it.
   The widget already builds every headless prompt in `assistant.py`;
   retrieval happens there and the chunks arrive already in the prompt. This
   needs no new tool permissions, which matters, because widening that set is
   not a thing to do casually.

## What was right in the research, and should be reused

The corpus was sized before the recommendation was made. The model choice was
corrected down from ~600M parameters to 33M once the hardware was considered.
The ONNX-not-torch constraint was spotted from the existing `onnx-asr[cpu]`
dependency. A vector index was refused at this scale in favour of brute-force
cosine in numpy. The reranker was dropped as a cross-encoder that costs a
forward pass per candidate. Carrying the low-confidence flag into results was
proposed unprompted.

A later build should start from all of that.

## The habit worth generalising

All three significant defects found on 9 September were things that only ever
passed: a corrector branch that changed text without logging it, a Hub export
that returned an empty list without saying whether it found nothing or was
broken, and a test suite that wrote over the production export while every
assertion stayed green.

The temp-leak check added the same day was trusted only after deliberately
leaking a directory and watching it go red. That is the habit: **a check you
have never seen fail is not yet a check.**
