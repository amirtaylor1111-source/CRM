from notetaker.transcribe import Segment, correct_names, hhmmss, merge_tracks, render_markdown


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

    def test_empty_vocabulary_is_a_no_op(self):
        segment = Segment(0, 1, "Jain at Akme")
        assert correct_names([segment], []) == 0
        assert segment.text == "Jain at Akme"


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
