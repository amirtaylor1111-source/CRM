# Semantic search over the corpus: measured, and not yet

**9 September 2026. Not built, deliberately.** A tooling-research session
proposed embeddings and a reranker over the meeting corpus. The research was
sound and the answer is still no, for a reason that is measured rather than
argued. This note exists so the next session finds the measurement instead of
re-deriving the design.

## The proposal

Local ONNX embeddings over the corpus, retrieval feeding `/prep`, `/ask` and
`/live-brief`. `BAAI/bge-small-en-v1.5`, 33M parameters, about 35 MB int8,
chosen because `onnx-asr[cpu]` already puts onnxruntime in the dependency
tree and nothing here uses torch. Roughly 900 chunks of 256 tokens. Storage
as a SQLite table beside `store.py`, brute-force cosine in numpy, no FAISS
and no new service. Chunking on `transcript.json` segment boundaries so a hit
keeps `start_ms` and can deep-link into the audio.

None of that is wrong. The model sizing, the ONNX-not-torch constraint, the
refusal to add a vector index at this scale, and carrying the low-confidence
flag through into results were all correct, and a later build should start
from them.

## Why not: the whole corpus fits in a prompt

Measured on the real repo, 26 meetings, at roughly four bytes per token.

| | Size | Tokens |
|---|---|---|
| Every `notes.md` in the corpus | 64 KB | ~16k |
| Every transcript in the corpus | 369 KB | ~94k |
| Largest single transcript | 102 KB | ~26k |
| Largest single `notes.md` | 12 KB | ~3k |
| `/prep`, heaviest contact, notes only | | ~2k |
| `/prep`, heaviest contact, notes and transcripts | | ~21k |

**There is no query this system can be asked that does not fit in context.**
`/ask` is scoped to one meeting and the largest is 26k tokens. `/prep` on the
heaviest contact is 2k tokens of notes. Even concatenating every transcript
ever recorded is 94k.

Retrieval would therefore be selecting a subset of something that could be
passed whole. It cannot improve recall, because nothing is being dropped for
want of room. It can only add a way to drop the right chunk.

## The subtle error worth not repeating

The research argued that 900 chunks is past the point where grep works, and
that is true: grep misses a transcript that says "the water's really hard
round here" when the question is about water hardness.

But "grep is insufficient" and "a vector index is necessary" are different
claims. At this size the fix is to hand the model the text and let it do the
semantic matching, which is the thing it is best at. Building a second
semantic system in front of the first one buys nothing until the text stops
fitting.

## The cost that would have been invisible

`/live-brief` runs every couple of minutes of speech, and each run already
spawns a Claude process on Amir's subscription. Putting retrieval in the
prompt builder adds retrieved chunks to every one of those prompts, on every
call, permanently, to select from a corpus that fits anyway. A recurring,
invisible cost is the worst kind to take on speculatively.

## What would change the answer

**When one unit of work stops fitting in the context window.** Concretely:

- any single contact's meetings exceed the window, or
- `/ask` on one meeting does.

On today's numbers the heaviest meeting contributes about 18k tokens of
transcript, so a contact would need roughly ten recorded meetings before
`/prep` on that person stopped fitting. Nobody is close; participant lists
are sparse and most contacts appear once.

Re-run the measurement rather than trusting this table. The script is four
lines: sum `notes.md` and `transcript.md` sizes per meeting, group by
participant, divide by four.

## If it is built later, two things carry forward

**Retrieval belongs in the Python prompt builder, not in a tool Claude
calls.** Headless runs have Read, Glob, Grep and Skill only, and a SQLite
table of float vectors is readable by none of them. So `/prep`, `/ask` and
`/live-brief`, the three surfaces that motivate the feature, are exactly the
three that could not query it. The widget is itself a Python process that
already builds every headless prompt in `assistant.py`; retrieval happens
there, and the chunks arrive already in the prompt. This needs no new tool
permissions, which matters, because widening that set is not a thing to do
casually.

**Embed notes and contact files before transcripts.** Notes are 64 KB against
369 KB of transcript, and they are the artifact where transcription errors
have already been repaired in context. Embedding raw transcript means
semantic search over words nobody said. This is the same decision the Hub
export made on 9 September and for the same reason; see
`specs/2026-09-09-meetings-to-hub.md`. If transcripts are embedded, the
low-confidence flag must travel with every chunk as a structural property,
never a convention, so an uncertain line cannot reach a summary with its
uncertainty stripped off.
