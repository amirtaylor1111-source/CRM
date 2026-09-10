"""Decision records live in exactly one place.

On 9 September a peer session proposed speaker diarization for phone calls,
a capability this repo had already spiked on 6 September with a better
implementation: the same pyannote model as a 6 MB ONNX file rather than a
torch dependency, on the day the machine lost 4 GB to four PyTorch installs.

It did not miss the spike by failing to look. It read `docs/superpowers/`,
saw `plans/`, `specs/` and `spikes/`, and reasonably concluded it had seen
the decision record. The diarization spike was in `docs/spikes/`, one level
up, under a same-named directory in a different root.

A convention that is only mostly true is worse than none, because it is
trusted. This keeps it true.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
HOME = DOCS / "superpowers"

#: The kinds of record that belong under docs/superpowers/ and nowhere else.
KINDS = ("spikes", "plans", "specs")


class TestOnePlaceForDecisions:
    @pytest.mark.parametrize("kind", KINDS)
    def test_no_second_home_for_this_kind(self, kind):
        strays = [
            p for p in DOCS.rglob(kind)
            if p.is_dir() and p.parent != HOME
        ]
        assert not strays, (
            f"{kind}/ exists outside docs/superpowers/:\n  "
            + "\n  ".join(str(p.relative_to(REPO)) for p in strays)
            + f"\n\nDecision records live in docs/superpowers/{kind}/ only. A "
              "second directory of the same name splits the set, and anyone "
              "who reads docs/superpowers/ then believes they have seen "
              "everything. That is how a solved problem gets re-proposed."
        )

    def test_the_home_exists_and_holds_something(self):
        """A repo doing real work with no decision record is a gap, not a style."""
        assert HOME.is_dir()
        assert list(HOME.rglob("*.md")), "docs/superpowers/ is empty"

    def test_no_record_points_at_a_file_that_moved(self):
        """Catches the dangling link a move like this one leaves behind."""
        broken = []
        for doc in HOME.rglob("*.md"):
            text = doc.read_text(encoding="utf-8")
            for kind in KINDS:
                needle = f"docs/{kind}/"
                if needle in text:
                    broken.append(f"{doc.relative_to(REPO)} -> {needle}")
        assert not broken, (
            "a decision record references a path outside docs/superpowers/:\n  "
            + "\n  ".join(broken)
        )
