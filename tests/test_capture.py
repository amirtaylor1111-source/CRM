"""Recording lifecycle, driven by a fake audio device.

No sound hardware is needed. The fake yields float32 frames × channels
arrays exactly as soundcard's _Recorder.record() does, so the write loop,
the stop-flag handshake, WAV finalisation and one-track-failure resilience
all run for real.
"""

import json
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from notetaker import capture


class FakeRecorder:
    def __init__(self, fail_after=None):
        self.calls = 0
        self.fail_after = fail_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def record(self, numframes=None):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise OSError("device unplugged")
        time.sleep(0.005)
        # 440 Hz tone so the file is verifiably non-silent.
        t = np.arange(numframes, dtype=np.float32) / capture.SAMPLE_RATE
        return (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1).astype(np.float32)


class FakeDevice:
    def __init__(self, name, fail_after=None):
        self.name = name
        self.fail_after = fail_after
        self.isloopback = "loopback" in name.lower()

    def recorder(self, samplerate, channels=None, blocksize=None, exclusive_mode=False):
        assert samplerate == capture.SAMPLE_RATE
        assert channels == capture.CHANNELS
        return FakeRecorder(self.fail_after)


def _run_recording(meeting_dir, mic, loopback, seconds=0.3):
    """Start in a thread, stop via the flag from 'another process', return state."""
    result = {}

    def target():
        result["state"] = capture.start_recording(meeting_dir)

    thread = threading.Thread(target=target)
    thread.start()
    time.sleep(seconds)
    tracks = capture.stop_recording(meeting_dir, timeout=5)
    thread.join(timeout=5)
    assert not thread.is_alive(), "recorder did not stop on the flag"
    return result["state"], tracks


@pytest.fixture
def devices(monkeypatch):
    holder = {"mic": FakeDevice("Microphone Array"),
              "loop": FakeDevice("Speakers (loopback)")}
    monkeypatch.setattr(capture, "_default_devices",
                        lambda: (holder["mic"], holder["loop"]))
    return holder


class TestLifecycle:
    def test_records_two_valid_tracks_and_stops_on_flag(self, tmp_path, devices):
        state, tracks = _run_recording(tmp_path, devices["mic"], devices["loop"])
        assert sorted(Path(t).name for t in tracks) == ["mic.wav", "system.wav"]
        for track in tracks:
            with wave.open(track, "rb") as w:
                assert w.getframerate() == capture.SAMPLE_RATE
                assert w.getnchannels() == 1
                assert w.getsampwidth() == 2
                assert w.getnframes() > 0          # header finalised, not zero
        assert "ended_at" in state
        assert state["duration_seconds"] >= 0
        assert not (tmp_path / capture.STOP_FLAG).exists()   # cleaned up

    def test_state_file_lets_another_process_see_it(self, tmp_path, devices):
        result = {}
        thread = threading.Thread(
            target=lambda: result.update(s=capture.start_recording(tmp_path)))
        thread.start()
        time.sleep(0.15)
        assert capture.is_recording(tmp_path)
        state = json.loads((tmp_path / capture.STATE_FILE).read_text())
        assert state["pid"] > 0
        assert {t["name"] for t in state["tracks"]} == {"mic", "system"}
        capture.stop_recording(tmp_path)
        thread.join(5)
        assert not capture.is_recording(tmp_path)

    def test_one_track_dying_does_not_end_the_recording(self, tmp_path, devices):
        devices["mic"].fail_after = 3
        state, tracks = _run_recording(tmp_path, devices["mic"], devices["loop"],
                                       seconds=0.4)
        names = {Path(t).name for t in tracks}
        assert "system.wav" in names                 # the healthy track survived
        by_name = {r["name"]: r for r in state["results"]}
        assert by_name["mic"]["error"]                # and the failure was recorded
        assert not by_name["system"]["error"]

    def test_mic_absent_records_system_only(self, tmp_path, monkeypatch):
        loop = FakeDevice("Speakers (loopback)")
        monkeypatch.setattr(capture, "_default_devices", lambda: (None, loop))
        state, tracks = _run_recording(tmp_path, None, loop)
        assert [Path(t).name for t in tracks] == ["system.wav"]

    def test_no_devices_is_an_actionable_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(capture, "_default_devices", lambda: (None, None))
        with pytest.raises(capture.CaptureError, match="mtg doctor"):
            capture.start_recording(tmp_path)

    def test_stop_with_nothing_running_is_harmless(self, tmp_path):
        assert capture.stop_recording(tmp_path) == []


class TestWavRepair:
    def test_repairs_a_header_from_a_killed_writer(self, tmp_path):
        path = tmp_path / "cut.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x01" * 16000)
        # Simulate death before close(): zero the RIFF and data size fields.
        with path.open("r+b") as fh:
            fh.seek(4); fh.write(b"\x00\x00\x00\x00")
            fh.seek(40); fh.write(b"\x00\x00\x00\x00")
        with pytest.raises(wave.Error):            # genuinely unopenable as-is
            wave.open(str(path), "rb")
        assert capture.repair_wav(path) is True
        with wave.open(str(path), "rb") as w:
            assert w.getnframes() == 16000         # audio recovered

    def test_correct_header_is_left_alone(self, tmp_path):
        path = tmp_path / "ok.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00" * 3200)
        assert capture.repair_wav(path) is False

    def test_not_a_wav_is_refused(self, tmp_path):
        path = tmp_path / "x.wav"
        path.write_bytes(b"definitely not riff data padded out" * 4)
        assert capture.repair_wav(path) is False


class TestMissingLibrary:
    def test_error_names_the_pip_install(self, monkeypatch):
        import builtins
        real = builtins.__import__

        def no_soundcard(name, *a, **k):
            if name == "soundcard":
                raise ImportError("nope")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", no_soundcard)
        with pytest.raises(capture.CaptureError, match="pip install soundcard"):
            capture.list_devices()
