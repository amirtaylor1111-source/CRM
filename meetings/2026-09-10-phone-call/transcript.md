---
generated_at: 2026-09-10T11:23:10Z
engine: onnx-asr
model: nemo-parakeet-tdt-0.6b-v3
expected_accuracy: 6.3%
duration: 00:24:49
tracks: system
speaker_method: separate audio tracks (attribution is exact)
segments: 384
low_confidence_segments: 26
names_corrected: 2
live: False
---

<!-- Machine-authored. Do not edit; write notes.md instead. -->


[00:01:09] **Caller:** Hello, everyone, good morning.
[00:01:11] **Caller:** Only more.
[00:01:12] **Caller:** Well after everybody's time.
[00:01:15] **Caller:** Mm.
[00:01:15] **Caller:** I don't know. Yeah.
[00:01:21] **Caller:** Good afternoon. I think it's afternoon for everyone.
[00:01:24] **Caller:** Yes, yes.
[00:01:25] **Caller:** That's correct.
[00:01:28] **Caller:** ⚠ Oh.
[00:01:29] **Caller:** Nice.
[00:01:29] **Caller:** Um
[00:01:31] **Caller:** My camera is not on today. Sorry, Shan, we can turn it off. Um that's our mommy is start. I I uh I've come up
[00:01:41] **Caller:** Microsoft meetings today and they have a camera on policy, so happy to disappear.
[00:01:47] **Caller:** ⚠ Oh.
[00:01:48] **Caller:** Yeah. Now you know what I look like, Rob. We've been working together for a couple of years.
[00:01:57] **Caller:** There we go. Let me check him quick now. He's the one that bought it
[00:02:06] **Caller:** Yeah, he's online, so he will join us shortly now.
[00:02:10] **Caller:** Okay.
[00:02:10] **Caller:** ⚠ Um
[00:02:13] **Caller:** Hey uh think we've all met, yeah.
[00:02:16] **Caller:** Yeah, um
[00:02:18] **Caller:** I sp I don't think you guys have met Hanveer.
[00:02:21] **Caller:** Um him and Mohammed work together.
[00:02:23] **Caller:** Um but other than that, everyone should have
[00:02:26] **Caller:** Should have met.
[00:02:28] **Caller:** Okay. Uh your your role then, maybe your face is warm.
[00:02:35] **Caller:** If you can show your face, I can't, so
[00:02:39] **Caller:** Hello, I
[00:02:41] **Caller:** Okay, cool. How does it say so your role in this would be just to assist Mohammed with the technical questions.
[00:02:51] **Caller:** All right. Yeah, exactly. Yeah. Yeah. And we're just helping us okay. We need any.
[00:02:56] **Caller:** Any head on?
[00:02:57] **Caller:** Only thing, yes.
[00:02:59] **Caller:** Perfect. Okay.
[00:03:00] **Caller:** Cool.
[00:03:01] **Caller:** Chirac, I think you can so basically guys what we'll do is we'll just
[00:03:07] **Caller:** Um
[00:03:08] **Caller:** Display.
[00:03:09] **Caller:** A depiction of our understanding.
[00:03:12] **Caller:** Of how everything.
[00:03:13] **Caller:** fits together from an architecture point of view.
[00:03:16] **Caller:** If you can just then contribute to that conversation and then just give us some nudges where we may be
[00:03:22] **Caller:** interpreting certain things in correctly.
[00:03:25] **Caller:** Then in terms of
[00:03:27] **Caller:** outcome than whatever architecture that we all agree on in terms of
[00:03:31] **Caller:** I think we will then
[00:03:34] **Caller:** Put that into our um
[00:03:35] **Caller:** Ted document or technical
[00:03:38] **Caller:** architecture document which will then later go in for review by the
[00:03:42] **Caller:** Okay, architect.
[00:03:44] **Caller:** I do wanna say though that
[00:03:46] **Caller:** Yeah.
[00:03:47] **Caller:** These forums focus
[00:03:50] **Caller:** It's not does not include the mobile app.
[00:03:54] **Caller:** work'cause that's it's with another team.
[00:03:57] **Caller:** So yeah, you may be called into another station soon just to unpack um low level topic flows for the
[00:04:07] **Caller:** For the mobile app.
[00:04:09] **Caller:** But for this conversation we'll just focus on the
[00:04:12] **Caller:** The telephony element of it, the Genesis environment.
[00:04:17] **Caller:** As well as um a green eps once um Privian is joined.
[00:04:22] **Caller:** where do we build that um push notification um layer
[00:04:28] **Caller:** Uh
[00:04:29] **Caller:** For the uh contacts to be written to the
[00:04:33] **Caller:** Mobile as well as the cleanup.
[00:04:34] **Caller:** I I don't think
[00:04:36] **Caller:** We agreed on that the last time the way.
[00:04:39] **Caller:** Couple of options one was the line manager.
[00:04:42] **Caller:** ⚠ I just fall.
[00:04:43] **Caller:** ⚠ Ask C Line Manager.
[00:04:45] **Caller:** So it's an option, but it is managed externally by vendor.
[00:04:50] **Caller:** If we are agrees to build that functionality in us through
[00:04:54] **Caller:** CSP or Genesis then if we have more control.
[00:04:58] **Caller:** But yeah, on that note then I'm gonna hand over to Shirag and yeah, it is a consolidated view just based on some of the um
[00:05:06] **Caller:** Diagrams that the mayor you shared last week.
[00:05:10] **Caller:** You say he gave us a bit of work'cause he didn't share the
[00:05:13] **Caller:** editable versions of those documents. So we almost had to recreate some of it.
[00:05:19] **Caller:** But uh it's okay.
[00:05:22] **Caller:** It was only my weekend. It wasn't Spoo's weekend, so don't stress that. Sorry about that shirt. I'm just kidding, I'm kidding. Okay.
[00:05:37] **Caller:** Yeah, R is joined so I think we all yeah.
[00:05:40] **Caller:** Sorry for Johnny Lee, but sorry, sure. No. Yeah, I think I mean in this in this con in this
[00:05:47] **Caller:** situation context matters, right? I think Spoo's been asking for
[00:05:52] **Caller:** Um a multitude of architectures and a couple of technicals which we didn't have.
[00:05:58] **Caller:** Um and again right this is by no means
[00:06:01] **Caller:** I could I have just taken what was provided to us.
[00:06:05] **Caller:** And put it together
[00:06:07] **Caller:** Based on
[00:06:09] **Caller:** I I don't want to say I know that this is not what your environment looks like, but
[00:06:13] **Caller:** It just gives it paints some some picture for the rest of the team, yeah. So
[00:06:19] **Caller:** ⚠ F
[00:06:20] **Caller:** Discussion today is purely around
[00:06:23] **Caller:** Well from my end, it's really around your environment, what this looks like.'Cause
[00:06:28] **Caller:** Unfortunately we have to take this to a very technical. So this forum is made up of
[00:06:34] **Caller:** Um security architects, cloud architects, enterprise architects, platform owners, et cetera.
[00:06:40] **Caller:** And what happens there is
[00:06:42] **Caller:** I mean w they're not too stressed about how your application runs, but they are stressed about
[00:06:48] **Caller:** Yeah, what does it look like in your wall?
[00:06:51] **Caller:** Um
[00:06:52] **Caller:** And you'll see by what we have on the left here.
[00:06:56] **Caller:** Um you know, they want us to go in quite a bit of detail, including
[00:07:00] **Caller:** What's
[00:07:01] **Caller:** Uh uh yeah, communication ports, etc. I'm not gonna ask IPs, but
[00:07:06] **Caller:** Ultimately, I mean you know, you were kind enough to share that diagram. Um
[00:07:11] **Caller:** And I've just taken each
[00:07:13] **Caller:** Each piece of it. So I think there were three, there was the push.
[00:07:17] **Caller:** Engage.
[00:07:18] **Caller:** Well
[00:07:18] **Caller:** Engage register.
[00:07:20] **Caller:** And engage P telemetry.
[00:07:22] **Caller:** So I've taken those three and I've just broken them down into and I know I've put them all in one A Z, which is definitely not
[00:07:28] **Caller:** Okay.
[00:07:29] **Caller:** ⚠ Fight.
[00:07:30] **Caller:** Problem here, if we were to start at the engage push architecture.
[00:07:34] **Caller:** And
[00:07:35] **Caller:** And again I'm not looking to fix this architecture or to to get this architecture in the
[00:07:40] **Caller:** format we need it in this session. It's merely just to give you the context of what the forum would be looking for.
[00:07:46] **Caller:** Um ultimately we have to get this passed, you know, on behalf of business. And in order to do that, we need the technical details. So
[00:07:54] **Caller:** If I look at it, I mean, as an example, your portal user, Cognito, et cetera, we know doesn't necessarily may look in the
[00:08:01] **Caller:** UAE region, but all the way in.
[00:08:04] **Caller:** Um
[00:08:05] **Caller:** You know, are these private subnets? What do these
[00:08:09] **Caller:** What do they look like? Is it
[00:08:11] **Caller:** What sits in the private, what's fronted?
[00:08:13] **Caller:** What security components do you have?
[00:08:16] **Caller:** um implementing today.
[00:08:18] **Caller:** What does the data layer look like? Observability as well. Is that a central role? Is it not?
[00:08:24] **Caller:** And does it encompass, you know, pretty much all three?
[00:08:27] **Caller:** Of these environments.
[00:08:29] **Caller:** Um
[00:08:31] **Caller:** At a low level, I mean I've got I've managed to figure out that you know you've also got a component of GCP logging in here.
[00:08:37] **Caller:** How does that integrate? What's the security components?
[00:08:41] **Caller:** that uh the controls and the security components that act as guard rails here.
[00:08:46] **Caller:** Um
[00:08:47] **Caller:** And I think
[00:08:49] **Caller:** That pretty much sums it up from
[00:08:52] **Caller:** My side. So I don't know. Are there any any questions?
[00:08:55] **Caller:** Just based on what I've run through now.
[00:09:05] **Caller:** So Chirag, uh you're asking here, okay, for example.
[00:09:08] **Caller:** ⚠ Um
[00:09:09] **Caller:** If if we can we can take you know one by one, okay, for example
[00:09:13] **Caller:** Uh you are just asked okay, uh are you using private sublin? Yes, we are using private sublime.
[00:09:18] **Caller:** Okay.
[00:09:19] **Caller:** And uh inside that we have uh
[00:09:22] **Caller:** Our our ECS cluster setup.
[00:09:24] **Caller:** Okay.
[00:09:25] **Caller:** And also we have data layer which is
[00:09:28] **Caller:** Uh secure and communicated with the ECS. Okay. We don't have any
[00:09:32] **Caller:** Uh I mean
[00:09:34] **Caller:** We are we don't have publicly accessible accessible that database. So within the system, ECS cluster can
[00:09:39] **Caller:** uh able to access the data then.
[00:09:41] **Caller:** Okay.
[00:09:42] **Caller:** Yeah.
[00:09:44] **Caller:** Mm-hmm.
[00:09:45] **Caller:** Yeah, and yeah. And that's exactly it, Moment. Thank you. So
[00:09:48] **Caller:** Ultimately.
[00:09:49] **Caller:** I need to depict that. I need to be able to show the foreign that okay, so right now we have an E C S cluster. The assumption is you know the slows
[00:09:57] **Caller:** I'm I'm assuming it lives in a private subnet because you don't want to expose
[00:10:01] **Caller:** Your cluster.
[00:10:02] **Caller:** But what sits above it, you know, how do we actually is it this load balancer that sits in a
[00:10:07] **Caller:** You know, in a different environment or how is this entire thing made up?
[00:10:11] **Caller:** Right. No, just based on the PDFs that you shared.
[00:10:15] **Caller:** And the little bit of you know reading that I've been uh I've been managed or I've managed to to complete.
[00:10:21] **Caller:** This is the view I kind of s I came up with.
[00:10:24] **Caller:** Um said okay at a high level let me leave it this way. I need
[00:10:28] **Caller:** Input from you.
[00:10:30] **Caller:** And the team um in order to get the
[00:10:35] **Caller:** ⚠ To me.
[00:10:38] **Caller:** Okay, understood. Uh okay. So we are almost uh everything is uh perfectly placed here on the diagram. Yeah.
[00:10:45] **Caller:** And the one thing I wanna correct here, we are not using uh UE data center, we are using RL data center.
[00:10:50] **Caller:** Okay.
[00:10:51] **Caller:** Okay, that was the one question from my side as well.
[00:10:54] **Caller:** Um just given the the past.
[00:10:57] **Caller:** few months right and what's happened with the UAE space. So
[00:11:02] **Caller:** I'll just make a note there. But okay, again.
[00:11:04] **Caller:** Can I share?
[00:11:06] **Caller:** This diagram. Yeah. Are you are you comfortable if I were to share this diagram for you guys to make the corrections?
[00:11:12] **Caller:** Based on what your architecture looks like.
[00:11:15] **Caller:** Uh yeah, sure we can. Okay. Uh
[00:11:19] **Caller:** Yes.
[00:11:20] **Caller:** If you share this uh we can correct and share.
[00:11:23] **Caller:** ⚠ Again.
[00:11:24] **Caller:** Yeah. Okay.
[00:11:25] **Caller:** Yeah, I think um from my end it's again, I I need to look I need to know what the
[00:11:31] **Caller:** P P C looks like the subnets, um private public.
[00:11:35] **Caller:** What is what controls are in place, what ports are being utilized, huh?
[00:11:40] **Caller:** for communications, et cetera.
[00:11:42] **Caller:** Not worried about how the app itself works, just worried about the controls and
[00:11:47] **Caller:** overlaying um guard jails that you guys have in your base'cause ultimately
[00:11:52] **Caller:** We will be asked to answer to these within the internal forum.
[00:11:56] **Caller:** So we need to ensure that we are ready.
[00:12:01] **Caller:** Okay, cool. And uh one more point I wanna highlight. So basically we have uh microservices based architecture. So
[00:12:07] **Caller:** Uh if you see uh you know here that put service or post worker you mentioned there, right?
[00:12:11] **Caller:** So these are different different uh I mean different different uh microservices.
[00:12:17] **Caller:** Okay.
[00:12:17] **Caller:** And the one thing I wanna mention here about the push worker. So for the for the push worker, the service
[00:12:24] **Caller:** Uh we uh and we are also you know given the uh I mean
[00:12:28] **Caller:** uh public submit because internally uh that particular service called to FCM for the push notification.
[00:12:34] **Caller:** ⚠ And the AP in
[00:12:36] **Caller:** ⚠ Uh sending post to the IST vis store here.
[00:12:39] **Caller:** Be uh given the move.
[00:12:41] **Caller:** Uh the public submit. So he actually loves high up, yeah, right. He doesn't love
[00:12:46] **Caller:** Oh I'm good.
[00:12:47] **Caller:** And yeah, I think I I think we got it, but
[00:12:50] **Caller:** Yeah, if the side the side inside the private settlement but be given the access to
[00:12:54] **Caller:** Go to the internet. Because yeah.
[00:12:57] **Caller:** And and that's the thing, right? We would need to depict that just to show the group that okay, this is where there's a little bit
[00:13:03] **Caller:** of uh outbound access or internal access, et cetera.
[00:13:07] **Caller:** In order to answer these questions.'Cause they are going to and I think spoo
[00:13:11] **Caller:** You can back me up here, so can drop and we are.
[00:13:14] **Caller:** Yes.
[00:13:15] **Caller:** It's a very grueling session to get these things in.
[00:13:19] **Caller:** Yeah, and I mean this is just one part of it, right? Yeah.
[00:13:23] **Caller:** ⚠ The more lamp is to
[00:13:25] **Caller:** Only to me the biggest one that we still need to go through.
[00:13:29] **Caller:** In terms of that integration. But I as long as we have uh dancing the role.
[00:13:34] **Caller:** For the um
[00:13:35] **Caller:** Let's call it.
[00:13:36] **Caller:** the left hand side of the picture, which is really this conversation today.
[00:13:41] **Caller:** then at least when the time arrives where we have the mobile app one, then at least there's no question about the actual underlying architecture around this.
[00:13:51] **Caller:** Yeah.
[00:13:52] **Caller:** Sharaga, I do agree with the approach. Let's show the the draw aisle.
[00:13:56] **Caller:** Um and then
[00:13:58] **Caller:** If I meet the mirror between you guys then I'm sure who's gonna own it. And then maybe if you can just agree disagree on the timeline.
[00:14:07] **Caller:** When we can expect to have it back.
[00:14:10] **Caller:** Business check in session schedule for tomorrow Wednesday. Um I'm not
[00:14:16] **Caller:** Expecting that we have it ready.
[00:14:18] **Caller:** By then, but at least
[00:14:20] **Caller:** If we can just have an update to save the same.
[00:14:22] **Caller:** You're working on it to be done by a particular date.
[00:14:27] **Caller:** Um thanks, Spoo. So um just to clarify
[00:14:30] **Caller:** I'm not the engineer yet so um
[00:14:33] **Caller:** Muhammad will will um you know earn this work and work at Tavir on it.
[00:14:37] **Caller:** Um
[00:14:38] **Caller:** What sounds like a reasonable timeline from
[00:14:41] **Caller:** From your side, was anything you maybe check before you
[00:14:45] **Caller:** You provide that.
[00:14:46] **Caller:** Oh.
[00:14:47] **Caller:** Okay, so for example you shared this uh with me. So
[00:14:52] **Caller:** By tomorrow, tomorrow I will work on it. Maybe uh after tomorrow we can set up another call.
[00:14:57] **Caller:** Okay, so for us or alternatively we can provide our technical document, which is pretty much aligned with the same document being shared by our
[00:15:06] **Caller:** So what do you think?
[00:15:07] **Caller:** Uh.
[00:15:08] **Caller:** Uh actually we already save load of document, but now we have to uh provide the refined version with the accurate version with the table and we can start.
[00:15:18] **Caller:** Oh my god, okay.
[00:15:19] **Caller:** Yeah, so let's let's try work on a single doc. I know it can get large and easy, but uh
[00:15:25] **Caller:** For us it's better because every all the information is will be compiled and contained.
[00:15:31] **Caller:** in the vision that Shira or I would say. So just extend that to you. So please just try
[00:15:38] **Caller:** Work on that single version and then when you're done.
[00:15:41] **Caller:** And send it back to us for review. I'll send up something as a follow-up for us on Wednesday afternoon.
[00:15:48] **Caller:** And then uh yeah, just to do a review of that document.
[00:15:52] **Caller:** Okay, cool. Uh and also uh if you have uh any question in advance you can also mention uh or send with us. Okay, so
[00:15:59] **Caller:** Uh on Wednesday we can uh discuss those point also. Okay.
[00:16:03] **Caller:** Perfect.
[00:16:04] **Caller:** Then um
[00:16:06] **Caller:** Okay, so I'm gonna shift.
[00:16:07] **Caller:** Uh from uh Shan and then that
[00:16:10] **Caller:** Documents and then
[00:16:12] **Caller:** Uh Ryan, I wanna just
[00:16:14] **Caller:** Have the discussion again around the
[00:16:17] **Caller:** Was it an API or a webhook integration between
[00:16:21] **Caller:** one of our own primary systems towards um first around for the push notification.
[00:16:28] **Caller:** Last time we
[00:16:30] **Caller:** Discuss that that platform could be um
[00:16:33] **Caller:** C S P because that's where the
[00:16:36] **Caller:** The age is a dying and uh you have
[00:16:39] **Caller:** Full sight of the um
[00:16:41] **Caller:** As opposed to the dialogue.
[00:16:43] **Caller:** End to end.
[00:16:45] **Caller:** Uh so that could be another layer of um
[00:16:48] **Caller:** that we can explore just to build that um integration out to
[00:16:53] **Caller:** True and uh you still know that.
[00:16:56] **Caller:** ⚠ Wave Little or Waving.
[00:16:57] **Caller:** Had any other thoughts since then?
[00:17:00] **Caller:** Well I I believe this has been discussed quite a while ago, so there wasn't any
[00:17:05] **Caller:** meaningful uh discussions around this topic um in the last while. Uh but if I've called from the last discussion as well, there was still some decisions pending regarding the the great platform to do the integration. Um because each platform would not actually have an E to N V, unfortunately. So even CSP being the the platform we're there to start from we we
[00:17:24] **Caller:** uh visibility of containing details, et cetera. We for example don't have um visibility of the actual outbound numbers that will be used.
[00:17:31] **Caller:** Um for the calls going out.
[00:17:34] **Caller:** So that would be a cafe there. And similarly, um, with if the platform was something else, like for example Genesis or
[00:17:41] **Caller:** Um
[00:17:41] **Caller:** Potentially even the
[00:17:43] **Caller:** Umager, yeah. Um those obviously will have them also missing parts of information. So each
[00:17:50] **Caller:** Each one of these three potential systems as a platform would actually present issues in themselves. So I think that is the the last um
[00:17:59] **Caller:** The points off that we're supposed to still be decided on.
[00:18:02] **Caller:** Which I'm not sure, Rob, if you know of any other details that I'm not
[00:18:05] **Caller:** Maybe two, um, with regards to discussions around those topics.
[00:18:09] **Caller:** ⚠ No boss and
[00:18:12] **Caller:** Yeah, so so my view on it, Ryan and uh did mention this before you joined, right?
[00:18:19] **Caller:** Because
[00:18:20] **Caller:** CLI manager is uh managed by a third party entity, right?
[00:18:26] **Caller:** And um so I don't wanna really rely too much on them.
[00:18:31] **Caller:** ⚠ Mm.
[00:18:32] **Caller:** what we're doing here. Yes, obviously they go for the CLI.
[00:18:36] **Caller:** Randomization engine.
[00:18:38] **Caller:** But for this particular use case, because it's ring fence to outbound sales environment, which is
[00:18:45] **Caller:** Where yourself and Rob come in.
[00:18:48] **Caller:** ⚠ My
[00:18:49] **Caller:** Selfish.
[00:18:50] **Caller:** Her friends will be
[00:18:52] **Caller:** If we build some control engine for this
[00:18:55] **Caller:** It must be within your area so that you can
[00:18:59] **Caller:** My name's Jaden.
[00:19:01] **Caller:** In control of that environment.
[00:19:04] **Caller:** Enverage other systems like um say live manager that say you want to have
[00:19:10] **Caller:** size of CLIs that I use pick and pain for the day.
[00:19:13] **Caller:** That we so we can have that conversation with C L I manage to say guys for this day with C L is uh in rotation.
[00:19:21] **Caller:** How can we present that?
[00:19:22] **Caller:** to the to the mobile app but in terms of
[00:19:24] **Caller:** You know, the actual core function of it.
[00:19:27] **Caller:** I would
[00:19:29] **Caller:** ⚠ And
[00:19:29] **Caller:** And yeah, yeah, you I'll set up other sessions with maybe the three entities combined, but my preference will be
[00:19:36] **Caller:** Because it's a connect requirement, this it'll be best if it's placed in within that environment just from a control perspective.
[00:19:46] **Caller:** Provided this capacity, of course. Yeah.
[00:19:48] **Caller:** Yeah.
[00:19:51] **Caller:** Yeah, I think uh this would be also one of the items that we'll just need to take to our steering committee forum as well, Rob, I believe.
[00:19:58] **Caller:** Uh just to
[00:19:59] **Caller:** It on um
[00:20:01] **Caller:** Or input on some of the other concerns we also raised before, such as delays and so on and
[00:20:06] **Caller:** And uh breakout tactics when um
[00:20:08] **Caller:** you know, certain thresholds that get succeeded with regards to the integration portion and so on. And
[00:20:14] **Caller:** all the other risks involved as well with um information staying on the on the mobile apps and yeah there's all those other previous discussions we had around the topics. I do think we just need to reignite those discussions. They look the right for them. And then
[00:20:27] **Caller:** I guess we can come back after that to say whether this thing is something that the C SP T will
[00:20:32] **Caller:** Lunch.
[00:20:34] **Caller:** Yeah.
[00:20:35] **Caller:** Okay, so then um
[00:20:38] **Caller:** Uh are you gonna own that? And do we need to be in the room when you have those conversations? Or can you
[00:20:46] **Caller:** Maybe
[00:20:47] **Caller:** When we set up the Wednesday chicken
[00:20:51] **Caller:** For this forum, you think Wednesday is enough time for you to have
[00:20:55] **Caller:** Something bang on that.
[00:21:01] **Caller:** I can only comment on the technical parts there. No rock. I don't think that's efficient time. I mean it's here because I mean we can all play, I think.
[00:21:09] **Caller:** ⚠ Okay.
[00:21:10] **Caller:** Okay, it's it's it's uh the uh that's that's second week, something in September.
[00:21:14] **Caller:** Yeah.
[00:21:15] **Caller:** September the fifth.
[00:21:17] **Caller:** Um
[00:21:18] **Caller:** I can run run it past uh J D in the meantime, you know, in other stakeholders.
[00:21:23] **Caller:** So that it gets the attention.
[00:21:27] **Caller:** That we can get uh some direction before the end.
[00:21:30] **Caller:** Okay.
[00:21:31] **Caller:** So just uh so I'm just sharing my screen here.
[00:21:35] **Caller:** ⚠ Um
[00:21:36] **Caller:** So we talking about this
[00:21:38] **Caller:** Interface, yeah.
[00:21:42] **Caller:** So Mohammed will give us that complete view of what they've built here based on the document that we share.
[00:21:49] **Caller:** Which will answer that T box thing.
[00:21:53] **Caller:** In general Rob, we still need to answer this block, yeah.
[00:21:58] **Caller:** Um
[00:22:00] **Caller:** S CLI manager probably sits on top here in the initial
[00:22:04] **Caller:** Uh content delivery. Maybe that's the actual call, the CLI.
[00:22:09] **Caller:** But this um
[00:22:11] **Caller:** Integration towards space or Ion.
[00:22:13] **Caller:** That's still a big question mark.
[00:22:19] **Caller:** So there's uh
[00:22:20] **Caller:** Uh guys here, uh do you need any answer from my side?
[00:22:24] **Caller:** No, no. Okay. As to where we're gonna build the integration to a zero platform. We just need to just decision making.
[00:22:34] **Caller:** ⚠ conversation in taking any.
[00:22:37] **Caller:** All right, thanks.
[00:22:38] **Caller:** ⚠ Hmm.
[00:22:39] **Caller:** Uh I do have another question, Ryan Rob, but maybe I'll ask you offline. Just uh in terms of um
[00:22:47] **Caller:** ⚠ Yeah, I admit it's not.
[00:22:49] **Caller:** But okay, just for the forum then I'll set up the follow up session Wednesday, and then Mohammed um
[00:22:55] **Caller:** Uh ten view if you can then just have that updated architecture diagram for then for review.
[00:23:01] **Caller:** If we like it, we'll have
[00:23:02] **Caller:** A direction from Rob and Ryan in terms of where we're building the integration.
[00:23:08] **Caller:** If not then we'll just use that to
[00:23:10] **Caller:** Okay. Yeah.
[00:23:12] **Caller:** Confirm and agree on that architecture itself.
[00:23:16] **Caller:** Okay. Yeah.
[00:23:17] **Caller:** ⚠ Makes us. Um
[00:23:19] **Caller:** Sorry, Spoo, just just while we're all on the call, um, would the same time on Wednesday work for everyone?
[00:23:26] **Caller:** Yeah.
[00:23:29] **Caller:** Mo Mohammed Tandri, would that would that work for you?
[00:23:32] **Caller:** Yes, yes.
[00:23:33] **Caller:** Nice one for me.
[00:23:35] **Caller:** Yeah. Yeah.
[00:23:36] **Caller:** Okay.
[00:23:38] **Caller:** ⚠ Okay for my side.
[00:23:41] **Caller:** Yeah, I've got one small conflict, but it's fine. I'll I'll move it.
[00:23:45] **Caller:** So I'll just yeah.
[00:23:46] **Caller:** Same same time.
[00:23:48] **Caller:** Next week.
[00:23:49] **Caller:** Okay, not next week, Wednesday. Yeah. Sorry, Mohammed, I didn't I didn't yeah, did that does that work for you as well?
[00:23:57] **Caller:** Yeah, yeah, yeah. Okay, no, sorry, sorry about that. I didn't yeah. Okay, cool. That sounds perfect then.
[00:24:03] **Caller:** Yeah. Thanks guys. Perfect. Thank you.
[00:24:12] **Caller:** ⚠ W
