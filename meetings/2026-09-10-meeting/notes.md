# SMD Prep

**Date:** 2026-09-10 · **Duration:** 39m · **Present:** Amir, Paul Cross (Telnyx)

## TL;DR

- Agenda agreed for today's SMD session: open, ~20 minutes through the portal, then the testing/POC conversation. The **first** question decides the rest — does SMD have in-house devs? If they do, the walkthrough is config-focused; if not, it is feature-focused [00:15:27]–[00:16:31].
- Amir's own South African number is blocked on **company proof of address for 7 Queen Square** — an invoice or bill from the last three months. Paul has already checked the application and that is the only thing missing [00:37:51]–[00:38:17].
- On the demo, Paul should click call from outside the portal so the pricing page is not on screen, because SMD is quoted at roughly a 20% margin over the dollar price to cover exchange-rate risk [00:34:38]–[00:35:31].

## Decisions

- **Agenda for the SMD session**, as agreed with Paul [00:15:27]–[00:19:38]:
  1. Open, and establish who is on the call and whether SMD has in-house devs.
  2. ~20 minutes in the portal, showing how to build an agent. Config-focused if they build, feature-focused if Telnyx builds.
  3. Testing and POC scoping.
- **Show the differentiating features either way** — voice speed, background audio, punctuation, interruptions — plus the Telnyx course [00:16:35]–[00:17:04]. Amir: *"I think that would impress them. I think you guys do that really, really well."*
- **Paul scopes the POC live, and Amir defers to him on it.** A simple build Telnyx does in-house; anything complex goes to the verified third parties at no markup [00:18:44]–[00:18:57], [00:21:04]–[00:21:20]. Amir: *"I'm just gonna rely on you to judge that because I don't want to answer those questions for you in the [call]."*

## Action items

- [ ] **@me** — upload company proof of address for 7 Queen Square to the Telnyx portal: an invoice or bill from the last three months (due: today) [00:37:51]–[00:38:17]
- [ ] **@Paul** — approve the South African number once the document is in (due: unspecified) [00:37:51]
- [ ] **@Paul** — have the previous demo recording available, in case the new stakeholders want to hear what was played last time (due: today's session) [00:34:24]–[00:34:32]

## Open questions

- **Does SMD have in-house devs, and are they on the call?** This is the question the whole agenda hangs on and it is unanswered [00:15:54]–[00:16:05], [00:20:15].
- **What does "testing" actually mean to SMD** — their success criteria and timelines? Nobody knows yet, and Amir named it as the one key question of the session [00:17:40]–[00:18:09], [00:18:57]–[00:19:04].
- **Who else is SMD evaluating?** A LinkedIn post suggested more than one vendor, which Amir thought was reasonable [00:21:38]–[00:21:47].
- Eric had a lot of questions on the last call and it has been a while, so Paul expects more [00:23:20]–[00:23:35].

## Risks and concerns

- **The pricing page is the risk in the demo.** SMD is charged a ~20% margin over the dollar price to cover exchange-rate exposure on rand quotes. If they see the portal pricing mid-demo it invites a conversation Amir does not want to have in that session [00:34:53]–[00:35:39]: *"they see in the [portal] the pricing... we wouldn't be having this session."*
- **The window on SMD may be closing.** They are talking to other vendors and the last call was some time ago.

## Also discussed

- **Amir's side venture.** Self-funding voice agents for one or two small clients who would not pay for it themselves, to build case studies and use them to win larger business. A few thousand rand a month, or roughly $100–200, buys a fair volume of calls [00:13:52]–[00:15:15], [00:28:27]–[00:28:44]. Lead quality is the open variable; he is looking at free sources first, then a sales-enrichment tool such as Apollo [00:28:48]–[00:29:02].
- **Connecting Claude to Telnyx** is via the MCP server rather than a connector in the Claude UI, and Telnyx has a skill built from its agent-readable API docs that can be pasted in for product context [00:24:30]–[00:27:32].
- **Cartesia.** Amir rated their voices the best he has heard, above ElevenLabs, and expressive enough that most people would not know it was AI. Telnyx has spoken to them on the partnership side [00:32:14]–[00:33:50].
- **Whether AI takes these jobs.** Both landed on relationship-led roles going last. Paul noted Telnyx has already automated most day-to-day business development over email, chat and phone, and that the relationship half is what remains [00:31:25]–[00:32:10].

## Notable quotes

> "I'm okay with building something simple in there, but we just need to figure out what that actually looks like." — Paul [00:19:46]

> "The key thing is really just understanding who's building it, are they on the call, and then if we're building it, how simple is a POC for you." — Amir [00:20:54]

## About this record

Written from this repo's own recorder, running for the first time in a real call. Two things a reader should know:

- **The proper nouns are unreliable.** "Telnyx" was never transcribed correctly — it appears as Talonic, Talmudic, Taliban and Telnex — and "SMD" appears as "S and D" and "S D". They have been repaired here from context. 49 of 678 segments were flagged low-confidence.
- **One factual detail is uncertain and has been left out of the summary above.** Around [00:26:19]–[00:26:41] Amir describes a model picking "Kimi two point five over Kimi two point six" and calls it a red flag because caching is cheaper on the newer one. The word "Kimi" may be a mis-transcription. Fathom's summary of the same passage renders it as Claude v2.5 and v2.6, which are not versions that exist, so both records are unreliable here and neither should be quoted.
