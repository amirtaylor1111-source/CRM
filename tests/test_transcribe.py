import sys
import types
from collections import namedtuple

import pytest

from notetaker.transcribe import (
    Segment,
    _transcribe_parakeet,
    correct_names,
    hhmmss,
    merge_tracks,
    speaker_method,
    render_markdown,
)


class TestNameCorrection:
    VOCAB = ["Jane Doe", "Acme", "Priya Raghunathan", "Kubernetes", "Amir Taylor"]

    def test_fixes_misspelled_known_names(self):
        segment = Segment(0, 1, "I met Jain at Akme about kubernets")
        assert correct_names([segment], self.VOCAB) == 3
        assert "Jane" in segment.text
        assert "Acme" in segment.text
        assert "Kubernetes" in segment.text

    def test_records_every_substitution(self):
        segment = Segment(0, 1, "Akme said yes")
        correct_names([segment], self.VOCAB)
        assert segment.corrections == ["Akme -> Acme"]

    def test_does_not_corrupt_ordinary_words(self):
        text = "The team said the price was about right, so we share their view later"
        segment = Segment(0, 1, text)
        assert correct_names([segment], self.VOCAB) == 0
        assert segment.text == text

    def test_requires_matching_first_letter(self):
        # "wane" is close to "Jane" but starts differently: leave it alone.
        segment = Segment(0, 1, "the wane in demand")
        assert correct_names([segment], self.VOCAB) == 0

    def test_short_words_are_never_touched(self):
        segment = Segment(0, 1, "an ok day")
        assert correct_names([segment], self.VOCAB) == 0

    def test_an_ordinary_lowercase_word_is_left_alone(self):
        """The corrector's worst failure, from seven real meetings.

        Every one of these was a substitution it actually made, in a client
        transcript, against that meeting's own contact list.
        """
        vocab = ["Alex Cross", "Sean Horn", "Vollmer", "Landau", "Dror",
                 "Paul", "Monty Smythe", "Rael", "First National", "Frans"]
        text = ("we were able to see the costs, and I have seen the hourly rate "
                "land in the volume report, so drop the monthly pull rate and "
                "firstly rely on what was sent")
        segment = Segment(0, 1, text)
        assert correct_names([segment], vocab) == 0
        assert segment.text == text
        assert segment.corrections == []

    def test_a_lowercase_word_is_still_fixed_when_it_is_plainly_the_name(self):
        # "kubernets" is a spelling of Kubernetes, not a word that resembles it.
        segment = Segment(0, 1, "we run kubernets in production")
        assert correct_names([segment], self.VOCAB) == 1
        assert "Kubernetes" in segment.text

    def test_a_capitalised_word_is_still_repaired(self):
        # The model capitalises what it heard as a name, so that is where a
        # near miss is worth repairing.
        segment = Segment(0, 1, "Jain from Akme called")
        assert correct_names([segment], self.VOCAB) == 2
        assert segment.text == "Jane from Acme called"

    def test_a_possessive_keeps_its_ending(self):
        """Found on a real call: "Salvador's Quest" became "Salvador Quest".

        The word pattern treats an apostrophe as part of the word, so the
        possessive was compared against the bare name and lost its ending.
        """
        segment = Segment(0, 1, "that was Jane's idea")
        assert correct_names([segment], self.VOCAB) == 0
        assert segment.text == "that was Jane's idea"

    def test_a_misheard_possessive_is_repaired_with_its_ending(self):
        segment = Segment(0, 1, "that was Jain's idea")
        assert correct_names([segment], self.VOCAB) == 1
        assert segment.text == "that was Jane's idea"
        assert segment.corrections == ["Jain's -> Jane's"]

    def test_a_company_named_after_an_ordinary_word_does_not_capitalise_it(self):
        """Found on this repo's own CRM: a contact works at Capital Legacy.

        The exact-match branch rewrote every lowercase "capital" as the
        company, silently, because a case change was not logged as one.
        """
        segment = Segment(0, 1, "that is a capital idea and a future concern")
        assert correct_names([segment], ["Capital Legacy", "Future Forex"]) == 0
        assert segment.text == "that is a capital idea and a future concern"

    def test_a_case_only_repair_is_logged_like_any_other(self):
        segment = Segment(0, 1, "I spoke to jane about it")
        assert correct_names([segment], self.VOCAB) == 1
        assert segment.text == "I spoke to Jane about it"
        assert segment.corrections == ["jane -> Jane"]

    def test_empty_vocabulary_is_a_no_op(self):
        segment = Segment(0, 1, "Jain at Akme")
        assert correct_names([segment], []) == 0
        assert segment.text == "Jain at Akme"


class TestSpeakerMethod:
    """What the transcript claims about attribution has to be true."""

    def test_two_tracks_that_both_carried_speech_are_exact(self):
        segments = [Segment(0, 1, "hello", speaker="Me"),
                    Segment(2, 3, "hi", speaker="Them")]
        assert speaker_method(segments, ["mic", "system"]) == \
            "separate audio tracks (attribution is exact)"

    def test_a_silent_track_is_declared(self):
        """The headphones case, seen on a real run: everything on one track.

        On speakers, or with the microphone muted, both voices land in the
        system file under one label. The claim of exactness then reads as a
        guarantee the recording cannot make.
        """
        segments = [Segment(0, 1, "hello", speaker="Them"),
                    Segment(2, 3, "hi", speaker="Them")]
        method = speaker_method(segments, ["mic", "system"])
        assert "no speech on the Me track" in method
        assert "attribution is exact" in method     # still true of what is there

    def test_a_single_track_recording_claims_nothing_extra(self):
        # A phone import is one channel by nature; there is no second track
        # whose silence would mean anything.
        segments = [Segment(0, 1, "hello", speaker="Them")]
        assert speaker_method(segments, ["system"]) == \
            "separate audio tracks (attribution is exact)"


class TestMergeAndRender:
    def test_tracks_interleave_chronologically(self):
        merged = merge_tracks(
            {"mic": [Segment(0, 1, "hello"), Segment(4, 5, "sure")],
             "system": [Segment(2, 3, "hi there")]},
            {"mic": "Me", "system": "Them"},
        )
        assert [s.speaker for s in merged] == ["Me", "Them", "Me"]
        assert [s.start for s in merged] == [0, 2, 4]

    def test_speaker_comes_from_track_not_a_guess(self):
        merged = merge_tracks({"system": [Segment(0, 1, "x")]}, {"system": "Jane"})
        assert merged[0].speaker == "Jane"

    def test_low_confidence_is_flagged_in_markdown(self):
        segment = Segment(0, 1, "unclear", low_confidence=True)
        out = render_markdown(merge_tracks({"mic": [segment]}, {"mic": "Me"}), {})
        assert "⚠" in out

    def test_markdown_warns_against_editing(self):
        out = render_markdown([], {"model": "x"})
        assert "Do not edit" in out


def test_hhmmss():
    assert hhmmss(0) == "00:00:00"
    assert hhmmss(3661) == "01:01:01"
    assert hhmmss(-5) == "00:00:00"


class TestParakeetAdapter:
    """onnx-asr's VAD adapter yields segments from a generator, not a list.

    The chain was first written from the library's source and wrapped that
    generator in a list, which read as a single item with no text: the first
    real recording on Windows came back as a transcript with zero segments.
    These drive _transcribe_parakeet through a fake of exactly the shapes
    onnx-asr 0.12 returns, with no model or audio involved.
    """

    Result = namedtuple("TimestampedSegmentResult",
                        "start end text timestamps tokens logprobs")

    def _fake_onnx_asr(self, monkeypatch, results_factory):
        R = self.Result

        class Pipeline:
            def recognize(self, waveform, **kwargs):
                return results_factory(R)

        class Model:
            def with_vad(self, vad, **kwargs):
                return self

            def with_timestamps(self):
                return Pipeline()

        fake = types.ModuleType("onnx_asr")
        fake.load_model = lambda name, quantization=None, sess_options=None: Model()
        fake.load_vad = lambda name: object()
        monkeypatch.setitem(sys.modules, "onnx_asr", fake)

    def test_generator_of_segments_is_consumed(self, monkeypatch, tmp_path):
        def generator(R):
            yield R(1.8, 4.6, "This is the install test.", None, None, [-0.1, -0.2])
            yield R(5.4, 8.3, "The quick brown fox.", None, None, [-0.9, -1.1])

        self._fake_onnx_asr(monkeypatch, generator)
        segments = _transcribe_parakeet(tmp_path / "system.wav", "nemo-parakeet-tdt-0.6b-v3")
        assert [s.text for s in segments] == ["This is the install test.",
                                               "The quick brown fox."]
        assert (segments[0].start, segments[1].end) == (1.8, 8.3)
        assert not segments[0].low_confidence
        assert segments[1].low_confidence            # mean log-prob -1.0

    def test_list_of_segments_still_works(self, monkeypatch, tmp_path):
        self._fake_onnx_asr(monkeypatch, lambda R: [R(0, 1, "hello", None, None, [-0.1])])
        segments = _transcribe_parakeet(tmp_path / "mic.wav", "m")
        assert [s.text for s in segments] == ["hello"]

    def test_single_unsegmented_result_still_works(self, monkeypatch, tmp_path):
        self._fake_onnx_asr(monkeypatch, lambda R: R(0, 2, "one result", None, None, []))
        segments = _transcribe_parakeet(tmp_path / "mic.wav", "m")
        assert [s.text for s in segments] == ["one result"]
        assert not segments[0].low_confidence        # no log-probs: never flagged

    def test_empty_generator_gives_no_segments(self, monkeypatch, tmp_path):
        self._fake_onnx_asr(monkeypatch, lambda R: iter(()))
        assert _transcribe_parakeet(tmp_path / "mic.wav", "m") == []

    def test_fake_matches_the_real_result_shape(self):
        """Skips on a machine without onnx-asr; fails loudly if it changes shape."""
        import dataclasses

        adapters = pytest.importorskip("onnx_asr.adapters")
        real = adapters.TimestampedSegmentResult
        if dataclasses.is_dataclass(real):
            names = [f.name for f in dataclasses.fields(real)]
        else:
            names = list(getattr(real, "_fields", ()))
        assert names[: len(self.Result._fields)] == list(self.Result._fields)
