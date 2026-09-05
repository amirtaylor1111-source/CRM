---
name: meeting-notes
description: Write up a recorded meeting from its transcript into notes.md, and update the CRM contacts involved. Use when the user asks to write up a meeting, summarise a call, produce meeting notes, or says things like "what did we agree with Acme", "write up my last call", or "/notes".
---

# Writing up a meeting

You are turning a machine-made transcript into the record a person will
actually rely on. The transcript is roughly 92-97% accurate at the word
level; your notes should be effectively 100% accurate at the level that
matters, because you can repair word errors from context and the transcript
cannot.

## 1. Find the meeting

Unless the user named one, take the most recent. Read `meetings/index.json`
for the list, then work inside `meetings/<id>/`.

If `transcript.md` is missing, tell the user the meeting has not been
transcribed yet and to run `mtg transcribe`. Do not invent content.

## 2. Read before you write

Read, in this order:

1. `meetings/<id>/meeting.json` — participants, consent record, timings.
2. `meetings/<id>/transcript.md` — the frontmatter matters. It reports the
   engine, the expected accuracy, and how many segments came back
   low-confidence.
3. The `contacts/<slug>.md` file for each known participant, so you carry
   forward what is already known rather than restating it.

## 3. Repair, do not invent

The transcript labels speakers by which audio track they came from, so
attribution is reliable even where wording is not.

- **Fix obvious mis-transcriptions from context.** If the participant list
  says Priya Raghunathan and the transcript says "pre-ya raghu nathan", write
  the name correctly.
- **Segments marked `⚠` are low-confidence.** Treat their content as
  uncertain. If something consequential rests on one, quote it verbatim with
  its timestamp and say it needs checking, rather than asserting it.
- **Never invent an action item.** If nobody agreed to it, it does not go in
  the list. A plausible next step that was not actually discussed is the most
  damaging thing you can add, because the user will act on it.
- **Never edit `transcript.md`.** It is the machine-authored record and its
  value is that it is unmodified. Your output goes in `notes.md`.

## 4. Write notes.md

Use exactly this structure:

```markdown
# <Meeting title>

**Date:** YYYY-MM-DD · **Duration:** Nm · **Present:** names

## TL;DR

- Three bullets at most. What a busy person needs if they read nothing else.

## Decisions

- What was actually decided, and by whom. Omit the section if nothing was.

## Action items

- [ ] **@owner** — what they committed to (due: date or "unspecified")

## Open questions

- Things raised and left unresolved.

## Risks and concerns

- Only if real ones surfaced. Omit otherwise.

## Notable quotes

> "Verbatim quote." — Name [00:12:34]
```

Rules for the body:

- Cite `[HH:MM:SS]` for anything consequential, so every claim is checkable
  against the transcript in one click.
- Prefer a short verbatim quote to a paraphrase when money, dates,
  commitments or numbers are involved.
- Use `@me` as the owner for the user's own actions.
- Omit empty sections entirely. A heading with nothing under it is noise.
- Keep the whole thing skimmable. If it runs past a screen and a half, the
  TL;DR is not doing its job.

## 5. Update the CRM

For each participant:

- Add or update `contacts/<slug>.md`. Record durable facts only: role,
  company, stated preferences, relationships. Not what happened in this one
  meeting, which is what the meeting folder is for.
- **The region between `## Meetings` and `<!-- /meetings -->` is managed by
  the tool.** Everything outside it belongs to the human. Never rewrite the
  file wholesale; edit within the human's text, not over it.
- If the transcript reveals a participant not listed in `meeting.json`, add
  them to it.

## 6. Report back

Two or three sentences in chat: what the meeting covered, the action items
that landed on the user, and anything you flagged as uncertain. Then stop.
The notes file is the deliverable; do not paste it back into the chat.
