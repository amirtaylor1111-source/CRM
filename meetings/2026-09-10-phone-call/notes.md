# Discovery — branded calling architecture review

**Date:** 2026-08-24 · **Duration:** 24m · **Present:** Chirag (chairing), Spoo Msezane, Rob, Ryan, Mohammed, Tanveer, Shan

## TL;DR

- **This session was about getting an architecture diagram through Discovery's internal review forum**, not about fixing the architecture. Chirag needs the technical detail the forum demands, and said so plainly: *"I'm not looking to fix this architecture... it's merely just to give you the context of what the forum would be looking for"* [00:07:35].
- **One decision is still open and now has an owner path**: where the push-notification integration to First Orion gets built. CLI Manager, CSP and Genesys were all considered and each is missing part of the picture [00:17:00]–[00:19:46].
- **Follow-up set for Wednesday, same time**, with a single corrected architecture document from Mohammed's side [00:22:47]–[00:23:57].

## Decisions

- **One document, not two.** Mohammed offered to supply their own technical document alongside the diagram; Chirag asked for a single consolidated version instead: *"let's try work on a single doc... for us it's better because all the information will be compiled and contained"* [00:15:19]–[00:15:41].
- **Scope of this forum excludes the mobile app**, which sits with another team. Today covered telephony, the Genesys environment, and where the push-notification layer gets built [00:03:47]–[00:04:17].
- **Preference stated for building the control engine inside the outbound sales environment** rather than relying on CLI Manager, because CLI Manager is run by a third party and this use case is ring-fenced to outbound sales, so control should sit with Rob and Ryan's area [00:18:12]–[00:19:46].

## Action items

- [ ] **@Chirag** — share the editable architecture diagram with Mohammed's team for correction (agreed in the call) [00:11:04]–[00:11:25]
- [ ] **@Mohammed** — return a corrected, consolidated architecture document, working with Tanveer (due: before Wednesday) [00:14:27]–[00:15:41]
- [ ] **@Chirag** — set up the Wednesday follow-up, same time, and confirm the invite [00:22:47]–[00:23:57]
- [ ] **@Ryan** — take the outstanding integration concerns to the steering committee: delays, breakout tactics when thresholds are exceeded, and the risk of information residing on the mobile app (due: unspecified) [00:19:51]–[00:20:27]
- [ ] **@Rob** — run the integration-platform question past JD and other stakeholders ahead of the forum, to get direction early [00:21:18]–[00:21:30]

## What was covered

- **What the review forum will ask for.** It is made up of security, cloud and enterprise architects and platform owners. They are not interested in how the application works; they want the environment: VPC and subnet layout, what is public and what is private, what sits in front of what, communication ports, security controls, the data layer, and whether observability is central and covers all three environments [00:06:20]–[00:08:52].
- **What Mohammed's team confirmed.** Private subnets, an ECS cluster inside them, a data layer that is not publicly accessible and is reachable only from the cluster, and a microservices architecture. The push worker is the exception and needs outbound access, because it calls FCM for push notifications [00:09:05]–[00:12:57].
- **One factual correction to the diagram:** the data centre is not UAE. Chirag noted it specifically, given recent events in that region [00:10:38]–[00:11:02].
- **A GCP logging component** appears in the architecture and its integration and security controls are an open question for the forum [00:08:31]–[00:08:46].
- **Why the integration platform is unresolved.** None of the three candidates has the end-to-end view. CSP lacks visibility of the outbound numbers actually used for calls; Genesys and CLI Manager each miss different pieces [00:17:00]–[00:17:59].

## Open questions

- **Where the push-notification integration gets built.** Explicitly flagged as still undecided and described as "a big question mark" on the diagram [00:22:00]–[00:22:34].
- **Whether Wednesday is enough time** for the steering-committee input. One participant said it is not, and the relevant forum falls in the second week of September [00:20:55]–[00:21:23].
- Whether Rob and Ryan need to be in the room for the steering-committee conversations, or can be briefed after [00:20:35]–[00:20:47].

## Risks and concerns

- **Getting through the forum is expected to be hard.** Described in the call as *"a very grueling session to get these things in"* [00:13:15], and today's scope is only one part of what must pass.
- **The mobile-app architecture is a separate review still to come**, and the point of settling the underlying architecture now is so that it is not reopened then [00:13:23]–[00:13:51].
- **Editable source files were not shared last time**, so the team recreated diagrams by hand over a weekend [00:05:06]–[00:05:22]. Worth avoiding on the next exchange.

## About this record

Imported from a phone recording, so **there is one audio track and every line is labelled "Caller"**. Seven or more people were on this call. Attributions above are made from context — who was addressed, who answered, who owns what — and are safe where the exchange is unmistakable, but the labels themselves identify nobody. Anything consequential should be confirmed against the recording.

26 of 384 segments were low-confidence. Names are the weakest part: Chirag appears as both Chirag and Shirag, Tanveer as Hanveer and "ten view", Spoo as Spoo and Spoo's, and "the mayor" at [00:05:06] is almost certainly Amir. None of these people are in the CRM, so nothing corrected them automatically.
