"""Live transcription over a WAV that is still growing.

No model: a fake transcriber decodes "speech" from the audio itself. Each
spoken second k is written as a constant level that encodes k, followed by a
short gap, so the fake can report the absolute second it heard from any
window of the file. That is enough to check what matters: absolute times,
no repeats across the overlap, the held-back tail, the split of a segment
VAD joined across the committed line, and the file format `/notes` reads.
"""

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from notetaker import live, transcribe
from notetaker.live import LiveSegment, LiveTranscriber

SR = live.SAMPLE_RATE
SPOKEN = 0.8                       # each spoken second: 0.8 s of level, 0.2 s gap


def level(k):
    return (k % 40 + 1) / 64.0


def write_seconds(path: Path, seconds, speech):
    """Create or extend a WAV so it holds `seconds` of audio; `speech` says
    which whole seconds carry a spoken word."""
    if not path.exists():
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    have = max(0, (path.stat().st_size - live.HEADER_BYTES) // 2) // SR
    chunks = []
    for k in range(have, seconds):
        block = np.zeros(SR, dtype=np.float32)
        if k in speech:
            block[: int(SPOKEN * SR)] = level(k)
        chunks.append(block)
    if chunks:
        pcm = (np.concatenate(chunks) * 32767).astype("<i2").tobytes()
        with path.open("ab") as fh:
            fh.write(pcm)


class DecodingTranscriber:
    """Reports one segment per run of level, named for the second it encodes."""

    def __init__(self, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    def __call__(self, audio):
        self.calls.append(len(audio) / SR)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("model hiccup")
        out = []
        on = audio != 0
        i = 0
        while i < len(audio):
            if not on[i]:
                i += 1
                continue
            j = i
            while j < len(audio) and on[j]:
                j += 1
            k = int(round(float(audio[i]) * 64)) - 1
            out.append(LiveSegment(i / SR, j / SR, f"w{k}", tokens=[(i / SR, f"▁w{k}")]))
            i = j
        return out


class ScriptedTranscriber:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, audio):
        self.calls.append(len(audio) / SR)
        return self.responses.pop(0) if self.responses else []


def words(transcriber, track="mic"):
    return [s.text for s in transcriber.tracks[track].segments]


class TestGrowingFile:
    def test_first_pass_holds_back_the_tail(self, tmp_path):
        write_seconds(tmp_path / "mic.wav", 10, speech=range(10))
        t = LiveTranscriber(tmp_path, transcribe_fn=DecodingTranscriber(), threads=1)
        assert t.tick() == 9
        assert words(t) == [f"w{k}" for k in range(9)]        # w9 ends inside TAIL
        assert t.tracks["mic"].committed == pytest.approx(9.0)
        seg = t.tracks["mic"].segments[4]
        assert (seg.start, seg.end) == pytest.approx((4.0, 4.8))

    def test_later_passes_add_without_repeating(self, tmp_path):
        path = tmp_path / "mic.wav"
        write_seconds(path, 10, speech=range(20))
        fake = DecodingTranscriber()
        t = LiveTranscriber(tmp_path, transcribe_fn=fake, threads=1)
        t.tick()
        write_seconds(path, 20, speech=range(20))
        assert t.tick() == 10                                   # w9 .. w18
        assert words(t) == [f"w{k}" for k in range(19)]
        assert fake.calls[1] == pytest.approx(20 - (9.0 - live.OVERLAP))   # read from committed-OVERLAP
        seg = t.tracks["mic"].segments[12]
        assert (seg.start, seg.end) == pytest.approx((12.0, 12.8))         # absolute, not window-relative

    def test_finish_takes_the_tail_and_marks_the_files_final(self, tmp_path):
        path = tmp_path / "mic.wav"
        write_seconds(path, 20, speech=range(20))
        t = LiveTranscriber(tmp_path, transcribe_fn=DecodingTranscriber(), threads=1)
        t.tick()
        meta = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))["meta"]
        assert meta["live"] is True
        assert t.finish() == 20
        data = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
        assert data["meta"]["live"] is False
        assert data["meta"]["segments"] == 20
        assert [s["text"] for s in data["segments"]] == [f"w{k}" for k in range(20)]
        assert "[00:00:07] **Me:** w7" in (tmp_path / "transcript.md").read_text(encoding="utf-8")

    def test_silence_still_advances_the_line(self, tmp_path):
        path = tmp_path / "mic.wav"
        write_seconds(path, 10, speech=())
        t = LiveTranscriber(tmp_path, transcribe_fn=DecodingTranscriber(), threads=1)
        assert t.tick() == 0
        assert t.tracks["mic"].committed == pytest.approx(10 - live.TAIL_SILENCE)

    def test_too_little_new_audio_is_skipped(self, tmp_path):
        path = tmp_path / "mic.wav"
        write_seconds(path, 10, speech=range(10))
        fake = DecodingTranscriber()
        t = LiveTranscriber(tmp_path, transcribe_fn=fake, threads=1)
        t.tick()
        write_seconds(path, 10, speech=range(10))              # nothing new
        assert t.tick() == 0
        assert len(fake.calls) == 1

    def test_both_tracks_interleave_in_the_files(self, tmp_path):
        write_seconds(tmp_path / "mic.wav", 6, speech={1, 3})
        write_seconds(tmp_path / "system.wav", 6, speech={2, 4})
        t = LiveTranscriber(tmp_path, transcribe_fn=DecodingTranscriber(), threads=1)
        t.finish()
        md = (tmp_path / "transcript.md").read_text(encoding="utf-8")
        lines = [l for l in md.splitlines() if l.startswith("[")]
        assert lines == ["[00:00:01] **Me:** w1", "[00:00:02] **Them:** w2",
                         "[00:00:03] **Me:** w3", "[00:00:04] **Them:** w4"]


class TestCatchingUp:
    def test_a_pass_never_takes_more_than_the_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(live, "MAX_PASS_SECONDS", 10.0)
        write_seconds(tmp_path / "mic.wav", 35, speech=range(35))
        fake = DecodingTranscriber()
        t = LiveTranscriber(tmp_path, transcribe_fn=fake, threads=1)
        t.tick()
        assert fake.calls[0] == pytest.approx(10.0)
        assert t.backlog() == pytest.approx(35 - t.tracks["mic"].committed, abs=0.01)
        while t.backlog() > 3:
            t.tick()
        assert t.finish() == 35
        assert words(t) == [f"w{k}" for k in range(35)]

    def test_a_held_back_segment_keeps_its_first_word(self, tmp_path):
        """VAD may start the same segment a few hundred ms earlier when it
        hears it with more context; that is not a join, and the segment must
        not be split at the line and lose its opening word."""
        path = tmp_path / "mic.wav"
        write_seconds(path, 10, speech={7, 9})
        first = [LiveSegment(7.0, 7.8, "w7", tokens=[(7.0, "▁w7")]),
                 LiveSegment(9.0, 9.8, "w9", tokens=[(9.0, "▁w9")])]      # held: committed = 9.0
        again = [LiveSegment(8.7 - 6.0, 9.8 - 6.0, "w9",                  # 300 ms earlier
                             tokens=[(2.7, "▁w"), (3.0, "9")])]
        t = LiveTranscriber(tmp_path, transcribe_fn=ScriptedTranscriber([first, again]), threads=1)
        t.tick()
        write_seconds(path, 20, speech={7, 9})
        t.tick()
        assert words(t) == ["w7", "w9"]


class TestJoinedSegments:
    def test_a_segment_joined_across_the_line_is_split_there(self, tmp_path):
        """Pass 1 hears w7 and w8 apart; pass 2's window makes VAD join
        w7-w8-w9 into one segment starting before the committed line.
        Only the new words may be added, once."""
        path = tmp_path / "mic.wav"
        write_seconds(path, 10, speech={7, 8, 9})
        first = [LiveSegment(7.0, 7.8, "w7", tokens=[(7.0, "▁w7")]),
                 LiveSegment(8.0, 8.8, "w8", tokens=[(8.0, "▁w8")]),
                 LiveSegment(9.0, 9.8, "w9", tokens=[(9.0, "▁w9")])]   # held back
        # pass 2 reads from committed(9.0) - 3 = 6.0; times below are window-relative
        joined = [LiveSegment(7.0 - 6.0, 9.8 - 6.0, "w7 w8 w9",
                              tokens=[(1.0, "▁w7"), (2.0, "▁w8"), (3.0, "▁w9")]),
                  LiveSegment(11.0 - 6.0, 11.8 - 6.0, "w11", tokens=[(5.0, "▁w11")])]
        t = LiveTranscriber(tmp_path, transcribe_fn=ScriptedTranscriber([first, joined]), threads=1)
        t.tick()
        assert words(t) == ["w7", "w8"]
        write_seconds(path, 20, speech={7, 8, 9, 11})
        t.tick()
        assert words(t) == ["w7", "w8", "w9", "w11"]
        w9 = t.tracks["mic"].segments[2]
        assert (w9.start, w9.end) == pytest.approx((9.0, 9.8))

    def test_split_without_tokens_keeps_the_words(self):
        seg = LiveSegment(7.0, 9.8, "w7 w8 w9")
        part = live.split_at(seg, 9.0)
        assert (part.start, part.end, part.text) == (9.0, 9.8, "w7 w8 w9")
        assert live.split_at(LiveSegment(7.0, 8.0, "w7"), 9.0) is None

    def test_split_detokenises_sentencepiece(self):
        seg = LiveSegment(0.0, 3.0, "the install test",
                          tokens=[(0.1, "▁the"), (1.0, "▁in"), (1.2, "stall"), (2.0, "▁test")])
        assert live.split_at(seg, 0.9).text == "install test"
        assert live.split_at(seg, 1.1).text == "stall test"

    def test_split_detokenises_parakeets_leading_spaces(self):
        # As onnx-asr hands them over on this laptop: " M", "ont", "y", " Smythe"
        seg = LiveSegment(0.0, 3.0, "Monty Smythe from Open",
                          tokens=[(0.1, " M"), (0.2, "ont"), (0.3, "y"), (1.0, " Smythe"),
                                  (1.5, " from"), (2.0, " Open")])
        assert live.split_at(seg, 0.15).text == "onty Smythe from Open"
        assert live.split_at(seg, 0.9).text == "Smythe from Open"
        assert live._detokenize(["plain", "words"]) == "plain words"


class TestFailure:
    def test_an_error_is_kept_and_finish_refuses(self, tmp_path):
        path = tmp_path / "mic.wav"
        write_seconds(path, 10, speech=range(10))
        fake = DecodingTranscriber(fail_first=True)
        t = LiveTranscriber(tmp_path, transcribe_fn=fake, threads=1)
        assert t.tick() == 0
        assert "model hiccup" in t.error
        write_seconds(path, 20, speech=range(20))
        assert t.tick() > 0                                     # later passes still run
        with pytest.raises(live.LiveError):
            t.finish()

    def test_speech_seconds_count_and_reset(self, tmp_path):
        write_seconds(tmp_path / "mic.wav", 10, speech=range(10))
        t = LiveTranscriber(tmp_path, transcribe_fn=DecodingTranscriber(), threads=1)
        t.tick()
        assert t.new_speech_seconds() == pytest.approx(9 * SPOKEN, abs=0.01)
        t.reset_speech()
        assert t.new_speech_seconds() == 0


class TestFormat:
    def test_files_match_what_the_full_transcription_writes(self, tmp_path, monkeypatch):
        write_seconds(tmp_path / "mic.wav", 6, speech={1, 3})
        t = LiveTranscriber(tmp_path, transcribe_fn=DecodingTranscriber(), threads=1)
        t.finish()
        live_meta = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))["meta"]

        other = tmp_path / "full"
        other.mkdir()
        write_seconds(other / "mic.wav", 6, speech={1, 3})
        monkeypatch.setattr(transcribe, "available_backends", lambda: ["parakeet"])
        monkeypatch.setattr(transcribe, "_transcribe_parakeet",
                            lambda path, model, threads=0, progress=print:
                            [transcribe.Segment(1.0, 1.8, "w1")])
        transcribe.transcribe_meeting(other, progress=lambda m: None)
        full_meta = json.loads((other / "transcript.json").read_text(encoding="utf-8"))["meta"]

        assert set(live_meta) == set(full_meta) | {"live"}
        for key in ("engine", "model", "expected_accuracy", "speaker_method"):
            assert live_meta[key] == full_meta[key]
        head = (tmp_path / "transcript.md").read_text(encoding="utf-8").splitlines()[:1]
        assert head == ["---"]

    def test_partial_trailing_frame_is_ignored(self, tmp_path):
        path = tmp_path / "mic.wav"
        write_seconds(path, 1, speech={0})
        with path.open("ab") as fh:
            fh.write(b"\x7f")                                   # half a sample
        audio = live.read_new_audio(path, 0.0)
        assert len(audio) == SR


# --- the worker process --------------------------------------------------------

import os
import subprocess
import sys


def decoding_transcriber():
    """What MTG_LIVE_TRANSCRIBER points the worker at."""
    return DecodingTranscriber()


class TestWorkerProcess:
    @pytest.fixture
    def fake_model(self, monkeypatch):
        monkeypatch.setenv("MTG_LIVE_TRANSCRIBER", "tests.test_live:decoding_transcriber")
        monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parent.parent))

    def test_the_process_transcribes_a_growing_file(self, tmp_path, fake_model):
        meeting = tmp_path / "meetings" / "m1"
        meeting.mkdir(parents=True)
        write_seconds(meeting / "mic.wav", 10, speech=range(20))
        lp = live.LiveProcess(meeting, vocabulary=["Monty Smythe"], python=sys.executable)
        assert lp.open() is True, lp.error
        assert lp.tick() == 9 and lp.count() == 9
        assert lp.new_speech_seconds() == pytest.approx(9 * SPOKEN, abs=0.01)
        lp.reset_speech()
        assert lp.new_speech_seconds() == 0
        write_seconds(meeting / "mic.wav", 20, speech=range(20))
        assert lp.tick() == 10
        assert lp.new_speech_seconds() == pytest.approx(10 * SPOKEN, abs=0.01)   # reset reached the worker
        assert lp.backlog() < 3
        assert lp.finish() == 20
        data = json.loads((meeting / "transcript.json").read_text(encoding="utf-8"))
        assert data["meta"]["live"] is False and data["meta"]["segments"] == 20
        assert lp._proc is None                              # closed after finish

    def test_a_dead_worker_is_an_error_not_a_hang(self, tmp_path, fake_model):
        meeting = tmp_path / "meetings" / "m2"
        meeting.mkdir(parents=True)
        lp = live.LiveProcess(meeting, python=sys.executable)
        assert lp.open() is True, lp.error
        lp._proc.kill()
        lp._proc.wait(5)
        assert lp.tick() == 0
        assert "not running" in lp.error
        with pytest.raises(live.LiveError):
            lp.finish()

    def test_resume_is_passed_to_the_worker(self, tmp_path, fake_model):
        meeting = tmp_path / "meetings" / "m3"
        meeting.mkdir(parents=True)
        write_seconds(meeting / "mic.wav", 10, speech=range(10))
        first = live.LiveProcess(meeting, python=sys.executable)
        assert first.open(), first.error
        assert first.tick() == 9
        first.close(kill=True)                                # a widget crash
        second = live.LiveProcess(meeting, python=sys.executable)
        assert second.open(resume=True), second.error
        write_seconds(meeting / "mic.wav", 12, speech=range(12))
        second.tick()
        assert second.finish() == 12                          # 9 restored + 3 new, no repeats
        texts = [s["text"] for s in json.loads((meeting / "transcript.json").read_text(encoding="utf-8"))["segments"]]
        assert texts == [f"w{k}" for k in range(12)]

    def test_the_fallback_transcribes_the_files(self, tmp_path, fake_model):
        meeting = tmp_path / "meetings" / "m4"
        meeting.mkdir(parents=True)
        write_seconds(meeting / "mic.wav", 6, speech={1, 3})
        lp = live.LiveProcess(meeting, python=sys.executable)
        lp.transcribe_files()
        data = json.loads((meeting / "transcript.json").read_text(encoding="utf-8"))
        assert [s["text"] for s in data["segments"]] == ["w1", "w3"]
        assert data["meta"]["live"] is False
        assert lp._proc is None

    def test_the_protocol_in_process(self, tmp_path):
        import io

        meeting = tmp_path / "m5"
        meeting.mkdir()
        write_seconds(meeting / "mic.wav", 10, speech=range(10))
        commands = [{"cmd": "open", "meeting_dir": str(meeting), "vocabulary": [], "threads": 1},
                    {"cmd": "tick"}, {"cmd": "nonsense"}, {"cmd": "finish"}, {"cmd": "quit"}]
        stdin = io.StringIO("\n".join(json.dumps(c) for c in commands) + "\n")
        stdout = io.StringIO()
        os.environ["MTG_LIVE_TRANSCRIBER"] = "tests.test_live:decoding_transcriber"
        try:
            assert live.worker_main(stdin=stdin, stdout=stdout) == 0
        finally:
            del os.environ["MTG_LIVE_TRANSCRIBER"]
        replies = [json.loads(l) for l in stdout.getvalue().splitlines()]
        assert replies[0] == {"ok": True, "restored": 0}
        assert replies[1]["ok"] and replies[1]["added"] == 9
        assert not replies[2]["ok"] and "unknown" in replies[2]["error"]
        assert replies[3] == {"ok": True, "count": 10}
        assert replies[4] == {"ok": True}
