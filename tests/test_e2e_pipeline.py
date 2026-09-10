"""End-to-end through transcribe_meeting on real speech audio.

The Parakeet weights cannot be fetched in every environment, so inference is
stubbed — but with onnx-asr's own TimestampedSegmentResult class, so if the
library changes shape this test breaks rather than the user's first meeting.
Everything downstream of inference runs for real: merge, name correction
against the CRM vocabulary, confidence flagging, and rendering.
"""

import shutil
import wave
from pathlib import Path

import pytest

from notetaker import store, transcribe

FIXTURES = Path("/tmp/e2e")
onnx_adapters = pytest.importorskip("onnx_asr.adapters")


def _tone_wav(path: Path, seconds: float = 2.0):
    """A valid 16 kHz mono WAV, for environments without the espeak fixtures."""
    import math
    import struct

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / 16000)))
            for i in range(int(16000 * seconds))
        )
        w.writeframes(frames)


@pytest.fixture
def meeting(crm, monkeypatch):
    monkeypatch.setattr(store, "repo_root", lambda: crm)
    d = store.create_meeting("Acme renewal", ["Monty Smythe", "Priya Raghunathan"],
                             True, root=crm)
    store.link_contact(d, "Monty Smythe", root=crm, company="SoluGrowth")
    store.link_contact(d, "Priya Raghunathan", root=crm, company="Acme")
    store.link_contact(d, "Kagiso Mzizi", root=crm)
    for name in ("mic", "system"):
        src = FIXTURES / f"{name}.wav"
        if src.exists():
            shutil.copy(src, d / f"{name}.wav")
        else:
            _tone_wav(d / f"{name}.wav")
    return d


def fake_parakeet(path, model_name, threads=0, progress=print):
    """Return what onnx-asr returns, with realistic mis-transcriptions."""
    R = onnx_adapters.TimestampedSegmentResult
    if path.name == "mic.wav":
        raw = [
            R(0.4, 4.1, "Thanks for joining. I spoke to Monti Smyth at Solugroth yesterday",
              None, None, [-0.1, -0.2, -0.15, -0.9, -1.1, -0.3]),
            R(4.3, 8.0, "and the renewal with Akme is approved at the same rate.",
              None, None, [-0.1, -0.1, -0.2, -0.3]),
            R(8.2, 12.0, "I will send the paperwork to Pria Ragunathan by Friday.",
              None, None, [-0.2, -0.1, -0.8, -1.4, -1.2]),
        ]
    else:
        raw = [
            R(1.0, 3.5, "That works for us.", None, None, [-0.05, -0.1]),
            R(3.8, 7.0, "Ronan from Open still owes us the data storage policy.",
              None, None, [-0.1, -0.2, -0.1]),
            R(7.2, 10.5, "Can you chase Kagisso Mzizzi about the branded calling pilot",
              None, None, [-0.3, -1.5, -1.6, -0.2]),
        ]
    # Mirror the real adapter's conversion, so the same code path is exercised.
    out = []
    for item in raw:
        lp = item.logprobs or []
        conf = sum(lp) / len(lp) if lp else 0.0
        out.append(transcribe.Segment(item.start, item.end, item.text, confidence=conf,
                                      low_confidence=bool(lp) and conf < transcribe.LOW_CONFIDENCE))
    return out


class TestEndToEnd:
    def test_full_pipeline_on_real_audio(self, meeting, crm, monkeypatch):
        monkeypatch.setattr(transcribe, "available_backends", lambda: ["parakeet"])
        monkeypatch.setattr(transcribe, "_transcribe_parakeet", fake_parakeet)
        # Force the engine choice so the test is deterministic across machines.
        from notetaker import hardware
        monkeypatch.setattr(hardware, "recommend",
                            lambda hw=None, english_only=True: {**hardware.ENGINES["parakeet"],
                                                                  "key": "parakeet", "why": "test",
                                                                  "cpu_threads": 2})
        messages = []
        md = transcribe.transcribe_meeting(meeting, vocabulary=store.vocabulary(root=crm),
                                           speaker_names={"system": "Monty Smythe"},
                                           progress=messages.append)
        text = md.read_text(encoding="utf-8")

        # Speakers come from track origin, interleaved chronologically.
        assert "**Me:**" in text and "**Monty Smythe:**" in text
        me_first = text.index("**Me:**")
        them_first = text.index("**Monty Smythe:**")
        assert me_first < them_first            # mic segment at 0.4s precedes system at 1.0s

        # Name correction against the CRM repaired the mis-transcriptions.
        assert "Monty Smyth" in text or "Monty" in text
        assert "Acme" in text and "Akme" not in text
        assert "Priya" in text and "Pria" not in text
        assert "Raghunathan" in text and "Ragunathan" not in text
        assert "Kagiso" in text and "Kagisso" not in text
        assert "Mzizi" in text and "Mzizzi" not in text

        # Low-confidence segments are flagged for review.
        assert "⚠" in text
        assert "low_confidence_segments:" in text

        # Ordinary words survived untouched.
        assert "data storage policy" in text
        assert "same rate" in text

        # JSON sidecar carries provenance for every substitution.
        import json
        data = json.loads((meeting / "transcript.json").read_text(encoding="utf-8"))
        subs = [c for s in data["segments"] for c in s["corrections"]]
        assert any("Acme" in c for c in subs)
        assert data["meta"]["speaker_method"].startswith("separate audio tracks")
        assert data["meta"]["names_corrected"] >= 4

    def test_missing_audio_is_a_clear_error(self, crm, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        d = store.create_meeting("Empty", root=crm)
        with pytest.raises(transcribe.TranscribeError, match="No audio found"):
            transcribe.transcribe_meeting(d)

    def test_no_engine_is_a_clear_error_naming_the_fix(self, meeting, monkeypatch):
        monkeypatch.setattr(transcribe, "available_backends", lambda: [])
        with pytest.raises(transcribe.TranscribeError, match=r"onnx-asr\[cpu,hub\]"):
            transcribe.transcribe_meeting(meeting)
