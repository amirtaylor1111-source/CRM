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
- `questions`: up to four questions worth asking before the call ends,
  grounded in what was said and in the contact's history: an open item from
  a previous meeting they have not mentioned, a number or date left vague, a
  commitment without a due date, a person named but not on the call. Empty if
  nothing stands out.

Do not write any files.
