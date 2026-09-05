---
description: Build a client-facing deal room page from the meeting history
---

Build a deal room for: $ARGUMENTS

A single self-contained HTML page summarising everything known about a deal,
for the user to send or present. Assembled from the CRM, not from memory.

## Sources, in order

1. `contacts/*.md` for everyone at that company — names, roles, emails, plus
   whatever the user has written by hand below the managed block.
2. `notes.md` from every meeting those contacts are linked to, most recent
   first.
3. `transcript.md` where a claim needs a verbatim quote.
4. The Outlook thread, if a connector is available, for anything agreed over
   email rather than on a call.

## Rules

**Every fact must trace to a source.** Quotes verbatim from the transcript
with their `[HH:MM:SS]`. Email addresses from the mail thread or the contact
file. Nothing inferred and presented as recorded.

**Where the record is empty, say so.** A row reading "not yet named" is
useful. A plausible guess in that row is a liability, because the user may
send this to the client.

**Flag contradictions rather than resolving them silently.** If a contact
file and a transcript disagree about someone's role or employer, surface both
and say which source each came from. The user decides.

**Anything from a `⚠` segment is uncertain.** Quote it and mark it, or leave
it out.

## Structure

A title, the state of play in three sentences, then: the people involved and
who they work for; what has been agreed; what is outstanding and who owes it;
open questions; and a timeline of meetings with dates linking to the notes.

Write it as one HTML file into `artifacts/deal-room-<company>.html`, styled
to be readable and printable, with no external assets so it works when
emailed. Publish it as an artifact only if the user asks.

## Afterwards

Report what you drew on, and list every field left empty for want of a
source. That list is the useful output — it tells the user what to find out
before the next call.
