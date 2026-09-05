import json

from notetaker import store


class TestMeetings:
    def test_create_and_load(self, crm):
        d = store.create_meeting("Acme Q3", ["Jane Doe"], True, "told them", root=crm)
        meeting = store.load_meeting(d)
        assert meeting.title == "Acme Q3"
        assert meeting.consent_obtained is True
        assert meeting.participants[0].name == "Jane Doe"

    def test_consent_is_persisted_as_data(self, crm):
        d = store.create_meeting("X", [], False, "solo", root=crm)
        raw = json.loads((d / "meeting.json").read_text())
        assert raw["consent_obtained"] is False
        assert raw["consent_note"] == "solo"

    def test_same_day_collision_gets_suffix(self, crm):
        a = store.create_meeting("Standup", root=crm)
        b = store.create_meeting("Standup", root=crm)
        c = store.create_meeting("Standup", root=crm)
        assert len({a.name, b.name, c.name}) == 3
        assert b.name.endswith("-2") and c.name.endswith("-3")

    def test_unicode_title_is_safe_on_disk(self, crm):
        d = store.create_meeting("Café ☕ review", root=crm)
        assert d.exists()
        assert store.load_meeting(d).title == "Café ☕ review"

    def test_index_rebuilds_purely_from_disk(self, crm):
        store.create_meeting("One", root=crm)
        store.create_meeting("Two", root=crm)
        index_path = store.rebuild_index(root=crm)
        index_path.unlink()                      # index is never the truth
        data = json.loads(store.rebuild_index(root=crm).read_text())
        assert data["count"] == 2

    def test_resolve_by_partial_name(self, crm):
        store.create_meeting("Acme Renewal", root=crm)
        found = store.resolve_meeting("renewal", root=crm)
        assert found is not None and "renewal" in found.name


class TestContacts:
    def test_linking_twice_yields_one_line(self, crm):
        d = store.create_meeting("Call", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm)
        path = store.link_contact(d, "Jane Doe", root=crm)
        assert path.read_text().count("../meetings/") == 1

    def test_human_notes_below_managed_block_survive(self, crm):
        d1 = store.create_meeting("First", ["Jane Doe"], root=crm)
        path = store.link_contact(d1, "Jane Doe", root=crm)

        path.write_text(path.read_text().rstrip()
                        + "\n\nPrefers early calls.\nAllergic to slide decks.\n")

        d2 = store.create_meeting("Second", ["Jane Doe"], root=crm)
        store.link_contact(d2, "Jane Doe", root=crm)

        after = path.read_text()
        assert "Prefers early calls." in after
        assert "Allergic to slide decks." in after
        assert after.count("../meetings/") == 2

    def test_human_notes_above_managed_block_survive(self, crm):
        d = store.create_meeting("First", ["Jane Doe"], root=crm)
        path = store.link_contact(d, "Jane Doe", root=crm)
        text = path.read_text().replace("## Meetings",
                                        "Some intro the human wrote.\n\n## Meetings")
        path.write_text(text)

        d2 = store.create_meeting("Second", ["Jane Doe"], root=crm)
        store.link_contact(d2, "Jane Doe", root=crm)
        assert "Some intro the human wrote." in path.read_text()

    def test_retitled_meeting_updates_in_place(self, crm):
        d = store.create_meeting("Draft title", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm)
        meeting = store.load_meeting(d)
        meeting.title = "Real title"
        store.save_meeting(d, meeting)
        path = store.link_contact(d, "Jane Doe", root=crm)
        text = path.read_text()
        assert text.count("../meetings/") == 1
        assert "Real title" in text and "Draft title" not in text

    def test_frontmatter_fields_merge_not_clobber(self, crm):
        d = store.create_meeting("Call", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm, company="Acme")
        path = store.link_contact(d, "Jane Doe", root=crm, email="j@acme.com")
        text = path.read_text()
        assert "Acme" in text and "j@acme.com" in text


class TestVocabularyAndSearch:
    def test_vocabulary_collects_names_and_companies(self, crm):
        d = store.create_meeting("Call", ["Jane Doe"], root=crm)
        store.link_contact(d, "Jane Doe", root=crm, company="Acme")
        vocab = store.vocabulary(root=crm)
        assert "Jane Doe" in vocab and "Acme" in vocab
        assert "Jane" in vocab          # parts, so a stray surname still matches

    def test_search_finds_text_in_transcripts(self, crm):
        d = store.create_meeting("Call", root=crm)
        (d / "transcript.md").write_text("[00:00:01] **Them:** the renewal is approved")
        results = store.search("renewal", root=crm)
        assert results and "renewal" in results[0]["hits"][0]

    def test_search_returns_nothing_for_absent_term(self, crm):
        store.create_meeting("Call", root=crm)
        assert store.search("nonexistent", root=crm) == []


class TestAtomicWrite:
    def test_failed_write_leaves_original_intact(self, crm, monkeypatch):
        target = crm / "contacts" / "x.md"
        store._write_atomic(target, "original content")

        import os as os_module

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(os_module, "replace", boom)
        try:
            store._write_atomic(target, "replacement")
        except OSError:
            pass
        assert target.read_text() == "original content"
        # and no temp debris left behind
        assert not list(target.parent.glob(".tmp-*"))
