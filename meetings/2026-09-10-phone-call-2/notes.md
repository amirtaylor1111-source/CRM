# Duplicate of Discovery 1

**Date:** 2025-11-28 · **Not written up here.**

> **This is the same conversation as
> [`2026-08-27-discovery-1`](../2026-08-27-discovery-1/notes.md), imported a
> second time from a different audio file.** The write-up lives there. Read
> that one.

Both transcripts open on the same words — "We do the pilot", then the twenty
thousand and the CLI contact success rate — and run the same call. They differ
only as two encodings of one recording differ: 130 segments here against 128
there.

`mtg phone` is idempotent on a content hash, and it did its job. The two files
genuinely differ byte for byte, so they hashed differently and both came in.
Deduplicating on content rather than on bytes would need a different mechanism
and is not obviously worth building for one collision.

**Nothing here has been deleted.** Two records of one conversation is a
tidiness problem, not a data problem, and which copy to keep is Amir's call.
If one goes, keep `2026-08-27-discovery-1`: it is dated correctly, it is
already written up, and it is the one the CRM and the Hub export point at.

## Why the date on this folder is wrong

The directory is named for 10 September, the day it was imported, while the
meeting itself was 28 November 2025. `store.create_meeting` dates a folder
from `started_at` when it is given one, and `phone.import_recording` passes
it — so this was imported without a date and then had its `meeting.json`
corrected by hand afterwards, which is exactly the case CLAUDE.md warns
against. By then the folder was already named.

The same applies to `2026-09-10-phone-call`, which is really 24 August.
