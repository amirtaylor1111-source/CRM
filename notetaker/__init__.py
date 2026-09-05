"""Local, consent-first meeting notetaker that feeds Claude Code.

Capture and transcription run entirely on this machine. All summarisation
happens when Claude Code reads the transcript in a normal session, so there
is no API key and no per-token bill.
"""

__version__ = "0.1.0"
