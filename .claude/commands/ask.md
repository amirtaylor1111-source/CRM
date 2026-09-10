---
description: Answer a question about a meeting (the widget's ask box)
---

Answer a question about a meeting. The first word below is the meeting id;
the rest is the question:

$ARGUMENTS

Read `meetings/<id>/meeting.json`, `meetings/<id>/transcript.md` (it may be
live and partial), `meetings/<id>/notes.md` if it exists, and the
participants' `contacts/<slug>.md`.

## Answer the question and nothing else

This is read on a phone-sized panel, mid-call, by someone who is also talking
to another person. One or two sentences. Three if the answer genuinely has
three parts.

**Say nothing about the machinery.** No mention of transcripts, recordings,
segments, confidence, low-confidence markers, engines, files, tracks, tools,
or how you came to know the answer. The user knows a recording is running;
being told again costs them the seconds they have.

- Bad: "According to the transcript at [00:12:34], with the caveat that this
  segment was marked low-confidence, Paul appears to have said the figure is
  twenty thousand."
- Good: "Twenty thousand a month, though he said it quickly and it is worth
  confirming."

Note the good version keeps the doubt. Drop the vocabulary of the tooling,
never the uncertainty itself — a number the user repeats back wrongly costs
more than a hedge.

- Quote the person's own words when the answer is a number, a date, a price
  or a commitment. A short quote is shorter than a paraphrase and safer.
- Give a timestamp only when the question is about when something happened,
  or when the user is being pointed at a specific moment to go back to.
  Otherwise it is noise.
- If the answer is not in what was said, say so in one line. Do not reason
  toward a plausible answer. "He hasn't mentioned a date" is a useful answer;
  a guessed date is not.
- If the call is still going, what has not been said yet may simply not have
  come up. Say "not so far" rather than "no".

Later questions in this conversation are about the same meeting unless they
say otherwise. Do not write any files.
