# SMD Technologies — portal walkthrough and POC scoping

**Date:** 2026-09-10 · **Duration:** 62m · **Present:** Amir, Eric Cotton (SMD Technologies), Paul Cross (Telnyx), two SMD business development managers

## TL;DR

- **Eric defined the test, and it is smaller and more concrete than expected**: ~100 leads he has been in touch with over the last six months, called to find out whether the contact still works there, catch up, re-qualify, and book a meeting. Success is "does the concept work", not production volume [00:54:03]–[00:55:11].
- **Telnyx builds the first version in-house.** Eric wants it simple and is explicitly not interested in heavy integrations yet. The only one he cares about is Claude [00:57:01]–[00:57:19].
- **Follow-up booked for Friday next week, same time.** Amir and Paul both send Eric an email with next steps and the information needed; Eric prepares call scenarios and any scripts [00:59:55]–[01:01:10].

## Decisions

- **Start with Telnyx building the MVP, and bring in the verified partners only at production scale.** Amir set out the two options and Eric's answer put it in the simple category [00:55:55]–[00:57:35]. Amir: *"we have verified partners in India and Ukraine... we don't mark those fees up in any way. You can even contract directly if you'd like."*
- **Test on five numbers first, then expand toward the hundred.** Eric's own proposal, so a bad assumption is caught cheaply [01:00:12]–[01:00:26]: *"I don't wanna give it a hundred numbers and then it doesn't give the information we need."*
- **Amir agreed to test internally before any real customer is called** [01:00:30].
- **SMD contacts Amir directly, copying Paul** [00:06:53]–[00:07:07].

## Action items

- [ ] **@me** — email Eric the next steps and the information needed to build the POC (due: unspecified, said in the call as the immediate next step) [01:00:30]
- [ ] **@Paul** — email Eric next steps and what information is required, framed as "what you'd need if you were hiring someone to do this" (due: unspecified) [00:59:49]–[01:00:04]
- [ ] **@Eric** — prepare the call scenarios, and share any scripts SMD normally follows (due: before the follow-up) [00:58:45]–[00:59:09]
- [ ] **@me** — set up the follow-up for Friday next week, same time (due: this week) [01:00:37]–[01:01:10]

## What Eric actually wants the agent to do

Worth keeping separate from the agenda, because this is the requirement:

- Call ~100 leads from the last six months.
- Establish whether the person still works there, and if not, capture that. Eric's example: check whether a named contact has moved to another company [00:55:09]–[00:55:17].
- Catch up, re-qualify, and where there is scope, book a meeting with one of his BDMs or himself [00:54:19]–[00:54:43].
- The underlying goal is data cleanup as much as meetings: *"It's for the agent to help me clean this up"* [00:55:09].
- Beyond this division there are "a few thousand" further leads SMD has never worked through, which is the phase-two prize [00:55:26]–[00:55:44].

## Open questions

- **The exact use case and script are not yet defined**, and Paul named that as the blocker on building anything [00:58:01]–[00:58:30].
- **Timing of the follow-up is subject to the information arriving**, which Amir said explicitly when proposing Friday.
- The two BDMs were introduced but their names are not reliably captured in the recording. They are the people meetings would be booked with.

## Risks and concerns

- **The demo voice drew the one criticism that matters for this use case.** Eric found the default voice too fast and then monotone: *"she sounds very monotone... when you talk you don't have monotone, you go up and down a little bit"* [00:36:52]–[00:37:06]. Paul adjusted speed and switched voices, and expressive mode exists, but nobody landed on a setting Eric endorsed. For a call that opens by claiming to be a person from SMD, this is the difference between a pilot that works and one that gets hung up on.
- **Eric leaves for another meeting before the close** [00:59:43], so the follow-up date was agreed with him only briefly. Worth confirming in the email.

## Notable quotes

> "It's basically as an initial tester to see how it helps us to clean up the data, and to set up meetings. If it worked at all, that for me is the test." — Eric [00:54:43]

> "I want to keep it as simple as possible. I'm not interested in very heavy integrations. Not yet anyway." — Eric [00:57:10]

## About this record

Recorded on this repo's own recorder, second real call. Three things a reader should know:

- **Speaker labels are only two-way and this was a five-person call.** Everything from Eric, Paul and the two BDMs is labelled "Them", because attribution comes from which audio track the voice was on and every remote voice shares one track. Attributions above were made from context and are safe where the sense is unmistakable; do not read the labels themselves as identifying who spoke.
- **The demo audio is transcribed as speech.** The agent's own sample calls around [00:35:16] and [00:37:38] are the product talking, not anyone in the meeting.
- 71 of 1167 segments were low-confidence. "Telnyx" was mis-transcribed eleven times as Telnex, Talnyx, Telnix and Talonyx, and all were repaired automatically against the CRM. One correction, "Sany" to "Shan" at low confidence, may be wrong and nothing rests on it.
