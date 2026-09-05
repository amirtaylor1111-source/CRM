from notetaker.schema import (
    Meeting, Participant, parse_frontmatter, serialise_frontmatter, slugify,
)


class TestSlugify:
    def test_transliterates_unicode(self):
        assert slugify("Ámir Tàylor") == "amir-taylor"

    def test_collapses_punctuation(self):
        assert slugify("Q3 Review!! (final)") == "q3-review-final"

    def test_empty_never_yields_empty_path(self):
        assert slugify("") == "untitled"
        assert slugify("!!!") == "untitled"

    def test_truncates_on_word_boundary(self):
        slug = slugify("a" * 30 + " " + "b" * 50)
        assert len(slug) <= 60
        assert not slug.endswith("-")

    def test_cjk_does_not_produce_empty(self):
        # Non-latin text transliterates to nothing; must still be usable.
        assert slugify("会議") == "untitled"


class TestFrontmatter:
    def test_round_trip_preserves_types(self):
        meta = {"name": "Jane", "tags": ["a", "b"], "active": True, "count": 3}
        parsed, body = parse_frontmatter(serialise_frontmatter(meta, "body"))
        assert parsed == meta
        assert body == "body"

    def test_value_containing_colon_survives(self):
        meta = {"title": "Re: the thing"}
        parsed, _ = parse_frontmatter(serialise_frontmatter(meta, ""))
        assert parsed["title"] == "Re: the thing"

    def test_unicode_survives(self):
        meta = {"name": "Zoë Müller"}
        parsed, _ = parse_frontmatter(serialise_frontmatter(meta, ""))
        assert parsed["name"] == "Zoë Müller"

    def test_no_frontmatter_returns_whole_body(self):
        meta, body = parse_frontmatter("just some notes")
        assert meta == {}
        assert body == "just some notes"

    def test_unterminated_frontmatter_does_not_swallow_content(self):
        text = "---\nname: x\nstill going"
        meta, body = parse_frontmatter(text)
        assert body == text


class TestMeeting:
    def test_round_trip(self):
        meeting = Meeting(
            id="m1", title="T", started_at="2026-01-01T00:00:00Z",
            participants=[Participant(name="Jane", company="Acme")],
            consent_obtained=True,
        )
        restored = Meeting.from_dict(meeting.to_dict())
        assert restored.participants[0].name == "Jane"
        assert restored.consent_obtained is True
