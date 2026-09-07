---
description: Answer a question about a meeting (the widget's ask box)
---

Answer a question about a meeting. The first word below is the meeting id;
the rest is the question:

$ARGUMENTS

Read `meetings/<id>/meeting.json`, `meetings/<id>/transcript.md` (it may be
live and partial), `meetings/<id>/notes.md` if it exists, and the
participants' `contacts/<slug>.md`. Answer briefly, in plain prose, citing
`[HH:MM:SS]` from the transcript for anything factual. If the transcript does
not contain the answer, say so rather than guessing. Later questions in this
conversation are about the same meeting unless they say otherwise. Do not
write any files.
