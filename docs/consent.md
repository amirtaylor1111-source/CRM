# Telling people you are recording

## What to say

At the top of the call, before anything substantive:

> "Just so everyone knows, I'm recording this call so I can take notes
> afterwards. Let me know if you'd rather I didn't."

That is the whole thing. It takes four seconds, and in practice almost nobody
objects, because meeting recorders are ordinary now.

In a chat-only context:

> "Recording this one for notes — shout if you'd rather I didn't."

## Why the tool asks

`mtg start` shows you the line and asks you to confirm you have said it. The
answer is stored in `meeting.json` as `consent_obtained`, alongside a
timestamp.

That record exists because a recording without provenance is worth much less
later. If a transcript ever matters, the first question is how it was
obtained, and the file answers it.

`--solo` skips the prompt for recordings where nobody else is present, and
records that fact rather than claiming consent that was never given.

## The legal bit, briefly

Recording rules vary by where the participants are, not where you are.

- **One-party consent** covers most of the US and the UK: you being party to
  the conversation is enough.
- **All-party consent** applies in California, Florida, Illinois, Washington
  and several others, and across much of the EU: everyone has to agree.

Since you cannot always tell where the person on the other end is sitting,
and since the difference between the two regimes is one sentence at the start
of a call, the practical answer is to always say it. That is what the tool is
built around.
