---
description: Brief me mid-call from the live transcript (the widget runs this)
---

Brief me on the meeting in progress: $ARGUMENTS

This runs while the call is still going, every couple of minutes. Read
`meetings/<id>/meeting.json`, then `meetings/<id>/transcript.md` (it is live
and partial; its frontmatter says `live: True`), then `contacts/<slug>.md` for
each participant the CRM knows.

Return JSON only, matching the schema you were given:

- `summary`: one line on where the conversation is right now.
- `next_steps`: things someone has actually committed to so far. `owner` is
  "me", "them" or a name; `text` is what was agreed, in their words where
  money, dates or numbers are involved; `at` is the `HH:MM:SS` it was said.
  Never invent one. Fewer is better than padding. An empty list is the right
  answer when nothing has been agreed yet.
- `questions`: up to four questions the user should ASK, phrased ready to say
  out loud.

  **These are gaps, not a record.** The panel is headed "Ask them". Every
  entry is something nobody has said yet and the user needs before the call
  ends. It is not a list of what has been discussed, not a summary of
  questions either side already asked, and never a question the conversation
  has already answered.

  Test each one: if the user read it aloud right now, would it be a sensible
  thing to say next? If it would make them sound as though they had not been
  listening, it does not belong.

  Look for the gap, not the topic:

  - an open item from a previous meeting they have not raised
  - a number, date or scope left vague — "how much", "when", "how many"
  - a commitment with no owner or no due date
  - a person or company named but not on the call, whose agreement is needed
  - a decision being talked around without being made

  Phrase them as the user would say them: "When do you need the proof of
  address by?" rather than "Clarify the deadline for the proof of address".

  Empty is a good answer. Four padded questions are worse than one real one,
  because the user has to read all four mid-conversation to find out there
  was nothing.

Do not write any files.
