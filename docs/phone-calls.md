# Recording calls from your phone

Your Galaxy A55 can record cellular calls itself, and South Africa is one of
the regions where Samsung ships that feature enabled. This brings those
recordings into the CRM alongside your laptop meetings.

**Cellular calls only.** WhatsApp calls are not covered — see the bottom of
this page for why, and what to do instead.

## 1. Turn on call recording

On the phone: **Phone app → ⋮ → Settings → Record calls**.

Turn on **Auto record calls** if you want every call captured, or leave it
off and hit record during the ones that matter. Samsung saves recordings to
`Internal storage/Call`.

If that menu is missing, your handset's region code has the feature disabled
and there is no way to enable it without changing the firmware, which is not
worth doing.

## 2. Get the folder onto your laptop

Any of these works; pick whichever you already use.

**OneDrive** is the least effort, since Samsung phones ship with it. In the
OneDrive app add `Internal storage/Call` as a backup folder, and it appears
on the laptop under `%USERPROFILE%\OneDrive\Call`.

**A USB cable** works fine if you would rather not put call audio in the
cloud. Plug in, allow file transfer, copy the `Call` folder across.

**Samsung Cloud** or any sync tool you already trust is equally fine — the
importer only cares that the files land in a folder it can read.

## 3. Install ffmpeg, once

Phones record in AMR or M4A; the speech engine reads WAV. ffmpeg does the
conversion, and this is the only part of the tool that needs it.

```powershell
winget install Gyan.FFmpeg
```

Then close that terminal and open a new one, or it will not be on PATH yet.

## 4. Import

```powershell
mtg phone "$env:USERPROFILE\OneDrive\Call"
```

Each recording becomes a meeting: it reads the contact's name and the time
from the filename, converts the audio, transcribes it, and links the contact
in your CRM. Then write it up with `/notes` in Claude Code, exactly like a
laptop meeting.

Running it again only picks up what is new. Recordings are matched on
content, so a file that syncs twice under a different name is not imported
twice.

Add `--limit 10` to do only the newest ten, which is useful the first time if
you have months of history.

## What this cannot do

**WhatsApp calls.** Samsung's recorder cannot see them, and neither can any
other app. Android excludes voice-communication audio from the capture API
that apps are allowed to use, on purpose, and WhatsApp calls are additionally
end-to-end encrypted. This is not a gap that can be coded around.

**Take those on the laptop instead.** WhatsApp Desktop does voice and video
calls, and the laptop recorder treats it like any other app — same two-track
capture, same transcript quality, same write-up. That is the only way to get
a WhatsApp call into the CRM properly.

## A note on the second speaker

A phone recording is one mixed track, so both voices share it. The transcript
labels everything as the caller rather than splitting it, because guessing
who spoke would be worse than not claiming to know.

Laptop meetings do not have this problem: they record you and the far end to
separate files, which is what makes their speaker attribution exact.
