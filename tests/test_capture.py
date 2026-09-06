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
    def __init__(self, fail_after=None, realtime=False):
        self.calls = 0
        self.fail_after = fail_after
        self.realtime = realtime              # deliver at the true audio rate

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def record(self, numframes=None):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise OSError("device unplugged")
        time.sleep(numframes / capture.SAMPLE_RATE if self.realtime else 0.005)
        # 440 Hz tone so the file is verifiably non-silent.
        t = np.arange(numframes, dtype=np.float32) / capture.SAMPLE_RATE
        return (0.5 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1).astype(np.float32)


class FakeDevice:
    def __init__(self, name, fail_after=None, open_delay=0.0, realtime=False):
        self.name = name
        self.fail_after = fail_after
        self.open_delay = open_delay          # seconds the stream takes to open
        self.realtime = realtime
        self.isloopback = "loopback" in name.lower()

    def recorder(self, samplerate, channels=None, blocksize=None, exclusive_mode=False):
        assert samplerate == capture.SAMPLE_RATE
        assert channels == capture.CHANNELS
        time.sleep(self.open_delay)
        return FakeRecorder(self.fail_after, realtime=self.realtime)


def _run_recording(meeting_dir, mic, loopback, seconds=0.3):
    """Start in a thread, stop via the flag from 'another process', return state."""
    result = {}

    def target():
        result["state"] = capture.start_recording(meeting_dir)

    thread = threading.Thread(target=target)
    thread.start()
    deadline = time.time() + 5                 # let the recorder report in first;
    while not capture.is_recording(meeting_dir) and time.time() < deadline:
        time.sleep(0.01)                       # a cold first run can take a moment
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

    def test_slow_device_is_padded_to_the_shared_start(self, tmp_path, devices):
        """A mic that opens late must not produce a file that starts late.

        On the real laptop the microphone array takes over a second to open
        while the loopback is immediate; without padding, every line on the
        mic track would sort early against the system track in the merged
        transcript. The slow track gets leading silence back to the common
        start, so both files are the same length to within a block or two.
        """
        devices["mic"].open_delay = 0.4
        for device in devices.values():       # length only means something
            device.realtime = True            # at the real audio rate
        state, tracks = _run_recording(tmp_path, devices["mic"], devices["loop"],
                                       seconds=1.2)
        lengths = {}
        for track in tracks:
            with wave.open(track, "rb") as w:
                lengths[Path(track).name] = w.getnframes() / capture.SAMPLE_RATE
        assert abs(lengths["mic.wav"] - lengths["system.wav"]) < 0.3, lengths
        by_name = {r["name"]: r for r in state["results"]}
        assert by_name["mic"]["lead_seconds"] >= 0.25
        # Relative, not absolute: a loaded machine can delay the fast track's
        # first chunk too, and that is not what this test is about.
        assert by_name["mic"]["lead_seconds"] > by_name["system"]["lead_seconds"] + 0.25
        # The padding is silence and the real audio starts where the recorded
        # lead says it does, to within a millisecond (lead_seconds is rounded
        # to 3 places, which is 16 frames).
        with wave.open(str(tmp_path / "mic.wav"), "rb") as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        first_sound = int(np.flatnonzero(pcm)[0])
        lead = by_name["mic"]["lead_seconds"] * capture.SAMPLE_RATE
        assert abs(first_sound - lead) <= 16
        assert by_name["mic"]["frames"] == len(pcm)     # frames counts the pad


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


# --- the Windows packet loop, driven by scripted packets on a virtual clock ---


class VirtualClock:
    def __init__(self, start=100.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def _tone(nframes, offset):
    """16-bit-quantised tone, so it carries the exact zeros real devices do."""
    t = (np.arange(nframes) + offset) / capture.SAMPLE_RATE
    return (np.round(0.5 * np.sin(2 * np.pi * 440 * t) * 32767) / 32767).astype(np.float32)


def _pcm(samples):
    """The bytes _Timeline writes for these samples."""
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class ScriptedSource:
    """Packets as WASAPI would hand them over: ('wait', s) or (frames, flags, stamp)."""

    def __init__(self, script, clock, stop):
        self.script = list(script)
        self.clock = clock
        self.stop = stop
        self.delivered = []          # samples handed over, in order
        self.read_at = []            # the clock when each was handed over

    def read(self):
        if not self.script:
            self.stop.set()
            return None
        item = self.script.pop(0)
        if item[0] == "wait":
            self.clock.advance(item[1])
            return None
        if item[0] == "stop":              # the flag lands with packets still queued
            self.stop.set()
            return None
        nframes, flags, stamp = item
        samples = _tone(nframes, sum(len(s) for s in self.delivered))
        self.delivered.append(samples)
        self.read_at.append(self.clock())
        return samples, flags, stamp


@pytest.fixture
def vclock(monkeypatch):
    clock = VirtualClock()
    monkeypatch.setattr(capture, "_clock", clock)
    monkeypatch.setattr(capture.time, "sleep", clock.advance)   # waiting passes time
    return clock


def _run_packets(tmp_path, vclock, script):
    stop = threading.Event()
    source = ScriptedSource(script, vclock, stop)
    track = capture.Track("mic", tmp_path / "mic.wav", "fake")
    with wave.open(str(track.path), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(capture.SAMPLE_RATE)
        capture._record_packets(source, out, stop, track, origin=100.0)
    with wave.open(str(track.path), "rb") as w:
        data = w.readframes(w.getnframes())
    return track, source, data


class TestPacketTimeline:
    SR = capture.SAMPLE_RATE
    PKT = SR // 100                      # WASAPI delivers 10 ms packets

    def _stream(self, start, count, flags_first=0):
        """`count` packets stamped every 10 ms from `start`, arriving on time."""
        out = []
        for k in range(count):
            out.append(("wait", 0.01))
            out.append((self.PKT, flags_first if k == 0 else 0, start + k * 0.01))
        return out

    def test_on_time_packets_are_appended_verbatim_after_the_lead(self, tmp_path, vclock):
        track, source, data = _run_packets(tmp_path, vclock, self._stream(100.5, 20))
        lead = int(0.5 * self.SR)
        assert track.lead == 0.5                              # first stamp - origin
        assert data[: lead * 2] == bytes(lead * 2)             # silence to the lead
        audio = b"".join(_pcm(s) for s in source.delivered)
        assert data[lead * 2: lead * 2 + len(audio)] == audio  # byte-identical audio
        assert track.filled == 0 and track.overlap == 0 and track.discontinuities == 0

    def test_lost_interval_after_a_stall_becomes_exactly_that_much_silence(self, tmp_path, vclock):
        # 10 packets, then the device goes quiet for 3 s. The engine kept the
        # last 1 s in its buffer (stamped from 102.6) and lost the 2 s before.
        script = self._stream(100.5, 10) + [("wait", 3.0)]
        script += [(self.PKT, capture._DISCONTINUITY if k == 0 else 0, 102.6 + k * 0.01)
                   for k in range(100)]
        track, source, data = _run_packets(tmp_path, vclock, script)
        resume = int(2.6 * self.SR)                            # where 102.6 lands
        first_backlog = _pcm(source.delivered[10])
        assert data[resume * 2: resume * 2 + len(first_backlog)] == first_backlog
        assert track.filled == pytest.approx(2.0, abs=0.002)   # only the lost 2 s
        assert track.discontinuities == 1
        head = b"".join(_pcm(s) for s in source.delivered[:10])
        assert data[int(0.5 * self.SR) * 2:][: len(head)] == head   # untouched

    def test_a_paused_device_still_keeps_time(self, tmp_path, vclock):
        # The loopback with nothing playing delivers no packets at all.
        track, source, data = _run_packets(tmp_path, vclock, [("wait", 1.0)] * 5)
        assert track.frames == int(round((vclock() - 100.0) * self.SR))   # padded to the stop instant
        assert track.frames >= 5 * self.SR
        assert not any(data)
        assert track.lead == 0 and track.filled == 0          # never started: no audio to stand in for

    def test_unreliable_stamp_after_a_gap_is_placed_by_the_clock(self, tmp_path, vclock):
        script = self._stream(100.5, 5) + [("wait", 0.5), (self.PKT, capture._TIMESTAMP_ERROR, None)]
        track, source, data = _run_packets(tmp_path, vclock, script)
        # It began no later than one packet before it was read, so it lands
        # there: a hair after the 0.55 s the first five packets reached.
        pos = int(round((source.read_at[5] - 0.01 - 100.0) * self.SR))
        assert pos > int(0.5 * self.SR) + 5 * self.PKT
        assert data[pos * 2: pos * 2 + self.PKT * 2] == _pcm(source.delivered[5])
        assert track.filled < 0.05

    def test_a_packet_stamped_early_is_kept_and_counted(self, tmp_path, vclock):
        script = self._stream(100.5, 5) + [("wait", 0.5), (self.PKT, 0, 100.5 + 0.02)]
        track, source, data = _run_packets(tmp_path, vclock, script)
        assert len(source.delivered) == 6
        assert track.overlap == pytest.approx(0.03, abs=0.001)
        end = int(0.5 * self.SR) + 5 * self.PKT                # it lands at the file end
        assert data[end * 2: end * 2 + self.PKT * 2] == _pcm(source.delivered[5])
        assert track.frames == int(round((vclock() - 100.0) * self.SR))

    def test_stop_takes_what_the_engine_still_holds(self, tmp_path, vclock):
        # The flag lands while 20 packets are still queued in the engine.
        script = self._stream(100.5, 5) + [("stop",)]
        script += [(self.PKT, 0, 100.55 + k * 0.01) for k in range(20)]
        track, source, data = _run_packets(tmp_path, vclock, script)
        assert len(source.delivered) == 25
        lead = int(0.5 * self.SR)
        audio = b"".join(_pcm(s) for s in source.delivered)
        assert data[lead * 2: lead * 2 + len(audio)] == audio  # all of it, in order

    def test_first_packet_without_a_stamp_is_placed_by_the_clock(self, tmp_path, vclock):
        script = [("wait", 1.2), (self.PKT, capture._TIMESTAMP_ERROR, None)] + self._stream(101.21, 3)
        track, source, data = _run_packets(tmp_path, vclock, script)
        assert track.lead == pytest.approx(1.19, abs=0.02)     # read time less one packet
        lead = int(track.lead * self.SR)
        assert data[lead * 2: lead * 2 + self.PKT * 2] == _pcm(source.delivered[0])

    def test_every_track_ends_at_the_stop_instant(self, tmp_path, vclock):
        script = self._stream(100.5, 3) + [("wait", 1.0)]
        track, source, data = _run_packets(tmp_path, vclock, script)
        assert track.frames == int(round((vclock() - 100.0) * self.SR))
        assert track.frames > int(0.5 * self.SR) + 3 * self.PKT      # padded past the audio


class TestWriteFailures:
    def test_a_failed_write_skips_the_packet_and_the_track_goes_on(self, tmp_path, vclock):
        stop = threading.Event()
        script = [item for k in range(6) for item in (("wait", 0.01), (160, 0, 100.5 + k * 0.01))]
        source = ScriptedSource(script, vclock, stop)
        track = capture.Track("mic", tmp_path / "mic.wav", "fake")

        class Flaky:
            """A wave writer whose third data write fails."""

            def __init__(self, inner):
                self.inner, self.calls = inner, 0
                self._file = inner._file

            def writeframesraw(self, data):
                self.calls += 1
                if self.calls == 3:
                    raise OSError(22, "Invalid argument")
                self.inner.writeframesraw(data)

        with wave.open(str(track.path), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(capture.SAMPLE_RATE)
            capture._record_packets(source, Flaky(out), stop, track, origin=100.0)
        with wave.open(str(track.path), "rb") as w:
            frames = w.getnframes()
        assert len(source.delivered) == 6                    # the loop never stopped
        assert "1 packet(s) could not be written" in track.error
        assert frames == track.frames                        # the header was patched at close

    def test_the_header_is_patched_at_close_not_on_every_write(self, tmp_path, vclock):
        track, source, data = _run_packets(tmp_path, vclock, [("wait", 0.01), (160, 0, 100.5)] * 3)
        with wave.open(str(tmp_path / "mic.wav"), "rb") as w:
            assert w.getnframes() == track.frames and w.getnframes() > 0


class TimedSource:
    """An engine model on the real clock: 10 ms packets come due as time
    passes, a stall pushes everything after it later, an empty engine
    returns None. Two of these on one origin and one stop event exercise
    what the change exists for."""

    LATENCY = 0.02

    def __init__(self, open_delay=0.0, stall_at=None, stall_for=0.0):
        self.open_delay = open_delay
        self.stall_at = stall_at            # packet index the stall precedes
        self.stall_for = stall_for
        self.start = None
        self.delivered = 0

    def _stamp(self, k):
        shift = self.stall_for if (self.stall_at is not None and k >= self.stall_at) else 0.0
        return self.start + k * 0.01 + shift

    def read(self):
        if self.start is None:
            time.sleep(self.open_delay)
            self.start = capture._clock()
            return None
        stamp = self._stamp(self.delivered)
        if capture._clock() < stamp + 0.01 + self.LATENCY:
            return None                     # not due yet
        self.delivered += 1
        return _tone(capture.SAMPLE_RATE // 100, self.delivered * 160), 0, stamp


class TestTwoPacketTracks:
    def test_two_tracks_on_one_origin_end_the_same_length(self, tmp_path):
        origin = capture._clock()
        stop = threading.Event()
        sources = {"system": TimedSource(),
                   "mic": TimedSource(open_delay=0.3, stall_at=40, stall_for=0.3)}
        tracks = {n: capture.Track(n, tmp_path / f"{n}.wav", "fake") for n in sources}

        def run(name):
            with wave.open(str(tracks[name].path), "wb") as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(capture.SAMPLE_RATE)
                capture._record_packets(sources[name], out, stop, tracks[name], origin)

        threads = [threading.Thread(target=run, args=(n,)) for n in sources]
        for t in threads:
            t.start()
        time.sleep(1.5)
        stop.set()
        for t in threads:
            t.join(10)
        frames = {n: tracks[n].frames for n in sources}
        assert abs(frames["mic"] - frames["system"]) <= 2 * (capture.SAMPLE_RATE // 100)
        assert tracks["mic"].lead > tracks["system"].lead + 0.2
        assert tracks["mic"].filled == pytest.approx(0.3, abs=0.05)   # the stall, once
        assert tracks["system"].filled < 0.05
        for name, source in sources.items():
            with wave.open(str(tracks[name].path), "rb") as w:
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            assert np.count_nonzero(pcm) >= source.delivered * 150   # every packet landed


class FakeCaptureClient:
    """Enough of IAudioCaptureClient's vtable for _WasapiSource.read()."""

    def __init__(self, samples, flags=0, qpc=0, hr=0, count=None):
        self.samples = np.asarray(samples, dtype=np.float32)
        self.flags, self.qpc, self.hr = flags, qpc, hr
        self.count = len(self.samples) if count is None else count
        self.get_calls = 0
        self.released = []

        client = self

        class VTable:
            def GetBuffer(self_, this, data, count, flags, devpos, qpc):
                client.get_calls += 1
                data[0] = "buffer"
                count[0] = client.count
                flags[0] = client.flags
                qpc[0] = client.qpc
                return client.hr

        class Obj:
            lpVtbl = VTable()

        self.handle = [[Obj()]]

    class FFI:
        def __init__(self, client):
            self.client = client

        def new(self, ctype):
            return [0]

        def buffer(self, ptr, nbytes):
            assert ptr == "buffer"
            return self.client.samples.tobytes()[:nbytes]

    def source(self, channels=1, available=None):
        def check(hr):
            if hr != 0:
                raise RuntimeError(f"Error {hr:#x}")
        return capture._WasapiSource(
            self.handle, available or (lambda: self.count), self.released.append,
            check, self.FFI(self), channels)


class TestWasapiSource:
    def test_packet_samples_stamp_and_release(self):
        client = FakeCaptureClient(_tone(160, 0), qpc=12_345_678_900)
        samples, flags, stamp = client.source().read()
        assert np.array_equal(samples, client.samples)
        assert stamp == pytest.approx(1234.56789)               # 100 ns units
        assert client.released == [160]

    def test_nothing_available_means_no_get_buffer(self):
        client = FakeCaptureClient(_tone(160, 0))
        assert client.source(available=lambda: 0).read() is None
        assert client.get_calls == 0

    def test_silent_packet_is_zeros_and_still_released(self):
        client = FakeCaptureClient(_tone(160, 0), flags=capture._SILENT)
        samples, flags, stamp = client.source().read()
        assert not samples.any() and flags & capture._SILENT
        assert client.released == [160]

    def test_unreliable_stamp_keeps_the_audio(self):
        client = FakeCaptureClient(_tone(160, 0), flags=capture._TIMESTAMP_ERROR, qpc=5)
        samples, flags, stamp = client.source().read()
        assert stamp is None and np.array_equal(samples, client.samples)

    def test_buffer_empty_is_not_an_error(self):
        client = FakeCaptureClient(_tone(160, 0), hr=capture._BUFFER_EMPTY)
        assert client.source().read() is None

    def test_zero_frames_is_no_packet(self):
        client = FakeCaptureClient(_tone(160, 0), count=0)
        assert client.source().read() is None

    def test_failure_hresult_raises(self):
        client = FakeCaptureClient(_tone(160, 0), hr=-2004287484)      # AUDCLNT_E_OUT_OF_ORDER
        with pytest.raises(RuntimeError):
            client.source().read()

    def test_stereo_is_downmixed(self):
        stereo = np.repeat(_tone(160, 0), 2)                    # L R L R ...
        client = FakeCaptureClient(stereo, count=160)
        samples, flags, stamp = client.source(channels=2).read()
        assert len(samples) == 160
        assert np.allclose(samples, _tone(160, 0))

