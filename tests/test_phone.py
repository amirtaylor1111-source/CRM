"""Importing recordings the phone made itself."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from notetaker import cli, phone, store

SAST = timezone(timedelta(hours=2))


class TestFilenameParsing:
    @pytest.mark.parametrize("name,who,stamp", [
        ("Call recording Monty Smythe_260904_143012.m4a", "Monty Smythe", "2026-09-04T14:30:12"),
        ("Call_Ronan OHiggins_20260730_091500.m4a", "Ronan OHiggins", "2026-07-30T09:15:00"),
        ("20260904 143012 Kagiso Mzizi.m4a", "Kagiso Mzizi", "2026-09-04T14:30:12"),
        ("Monty Smythe_260904_143012.amr", "Monty Smythe", "2026-09-04T14:30:12"),
    ])
    def test_known_samsung_shapes(self, name, who, stamp):
        got_who, got_when = phone.parse_filename(name)
        assert got_who == who
        assert got_when.strftime("%Y-%m-%dT%H:%M:%S") == stamp

    def test_a_number_is_kept_as_a_number(self):
        who, _ = phone.parse_filename("Call recording +27821234567_260904_143012.m4a")
        assert who == "+27821234567"

    def test_unrecognised_name_guesses_nothing(self):
        # A wrong contact is worse than an unnamed call.
        assert phone.parse_filename("random-voice-memo.m4a") == ("", None)

    def test_impossible_date_is_rejected_not_coerced(self):
        assert phone.parse_filename("Call recording X_269999_143012.m4a") == ("", None)


class TestFileId:
    def test_same_content_same_id(self, tmp_path):
        a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
        a.write_bytes(b"identical audio"); b.write_bytes(b"identical audio")
        assert phone.file_id(a) == phone.file_id(b)

    def test_different_content_different_id(self, tmp_path):
        a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
        a.write_bytes(b"call one"); b.write_bytes(b"call two!")
        assert phone.file_id(a) != phone.file_id(b)


class TestDiscovery:
    def test_finds_audio_recursively_and_ignores_junk(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.m4a").write_bytes(b"x")
        (tmp_path / "sub" / "b.amr").write_bytes(b"x")
        (tmp_path / "notes.txt").write_text("not audio")
        (tmp_path / "thumb.jpg").write_bytes(b"x")
        found = {p.name for p in phone.find_recordings(tmp_path)}
        assert found == {"a.m4a", "b.amr"}

    def test_missing_folder_explains_where_to_look(self, tmp_path):
        with pytest.raises(phone.PhoneImportError, match="Internal storage"):
            phone.find_recordings(tmp_path / "nope")

    def test_one_audio_file_is_a_target_in_its_own_right(self, tmp_path):
        # Recordings that are not Samsung's own arrive one at a time, and
        # naming the file is the only way to say which one you mean.
        one = tmp_path / "Discovery-1.m4a"
        one.write_bytes(b"x")
        (tmp_path / "Sameer.m4a").write_bytes(b"y")
        assert phone.find_recordings(one) == [one]

    def test_a_file_that_is_not_audio_is_refused(self, tmp_path):
        junk = tmp_path / "notes.txt"
        junk.write_text("not audio")
        with pytest.raises(phone.PhoneImportError, match="not an audio recording"):
            phone.find_recordings(junk)


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Stand in for ffmpeg by writing a real, valid 16 kHz mono WAV."""
    def convert(source: Path, destination: Path):
        import wave
        with wave.open(str(destination), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)
    monkeypatch.setattr(phone, "to_wav", convert)


class TestImport:
    def test_imports_a_call_and_links_the_contact(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Call recording Monty Smythe_260904_143012.m4a"
        src.write_bytes(b"audio bytes")

        meeting_dir, status = phone.import_recording(src, root=crm, transcribe=False)
        assert status == "imported"
        meeting = store.load_meeting(meeting_dir)
        assert meeting.title == "Call with Monty Smythe"
        assert meeting.started_at.startswith("2026-09-04T14:30:12")
        assert [p.name for p in meeting.participants] == ["Monty Smythe"]
        assert (meeting_dir / "system.wav").exists()
        assert "monty-smythe" in store.list_contacts(root=crm)

    def test_consent_note_says_who_actually_recorded_it(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Call recording X_260904_143012.m4a"
        src.write_bytes(b"a")
        meeting_dir, _ = phone.import_recording(src, root=crm, transcribe=False)
        assert "phone's own dialer" in store.load_meeting(meeting_dir).consent_note

    def test_importing_twice_is_a_no_op(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Call recording Monty Smythe_260904_143012.m4a"
        src.write_bytes(b"audio bytes")
        phone.import_recording(src, root=crm, transcribe=False)
        meeting_dir, status = phone.import_recording(src, root=crm, transcribe=False)
        assert meeting_dir is None and status == "already imported"
        assert len(list((crm / "meetings").glob("*/"))) == 1

    def test_a_renamed_file_is_still_recognised_as_the_same_call(self, crm, fake_ffmpeg,
                                                                monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Call recording Monty Smythe_260904_143012.m4a"
        src.write_bytes(b"audio bytes")
        phone.import_recording(src, root=crm, transcribe=False)
        copy = crm / "Call recording Monty Smythe_260904_143012 (1).m4a"
        copy.write_bytes(b"audio bytes")          # same content, new name
        _, status = phone.import_recording(copy, root=crm, transcribe=False)
        assert status == "already imported"

    def test_a_number_does_not_become_a_contact(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Call recording +27821234567_260904_143012.m4a"
        src.write_bytes(b"a")
        phone.import_recording(src, root=crm, transcribe=False)
        assert store.list_contacts(root=crm) == []

    def test_unparseable_name_falls_back_to_the_file_time(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "voice-memo.m4a"
        src.write_bytes(b"a")
        meeting_dir, _ = phone.import_recording(src, root=crm, transcribe=False)
        meeting = store.load_meeting(meeting_dir)
        assert meeting.title == "Phone call"
        assert meeting.participants == []

    def test_folder_import_reports_counts(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        folder = crm / "Call"; folder.mkdir()
        for i, who in enumerate(["Monty Smythe", "Kagiso Mzizi"]):
            (folder / f"Call recording {who}_26090{i+1}_1200{i}0.m4a").write_bytes(
                f"audio {i}".encode())
        first = phone.import_folder(folder, root=crm, transcribe=False)
        assert first == {"found": 2, "imported": 2, "skipped": 0, "failed": 0,
                         "meetings": first["meetings"]}
        second = phone.import_folder(folder, root=crm, transcribe=False)
        assert second["imported"] == 0 and second["skipped"] == 2


class TestOverrides:
    """Recordings that are not Samsung's own carry their date in the file.

    `parse_filename` matches nothing in "Discovery-1.m4a", and renaming the
    file into a Samsung shape would smuggle in a `who` that becomes a title,
    a participant and a contact. So the caller supplies the title and the
    time it already knows, and the importer invents neither.
    """

    def test_the_given_title_and_time_beat_the_filename(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Discovery-1.m4a"
        src.write_bytes(b"audio bytes")

        meeting_dir, status = phone.import_recording(
            src, root=crm, transcribe=False,
            title="Discovery 1",
            when=datetime(2026, 8, 27, 10, 37, 16, tzinfo=SAST),
        )
        meeting = store.load_meeting(meeting_dir)
        assert status == "imported"
        assert meeting.title == "Discovery 1"
        assert meeting.started_at == "2026-08-27T08:37:16Z"

    def test_a_given_title_names_nobody(self, crm, fake_ffmpeg, monkeypatch):
        # Who was in the room is only knowable from the transcript, and a
        # wrong name here would poison store.vocabulary() for every meeting.
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Call recording Monty Smythe_260904_143012.m4a"
        src.write_bytes(b"audio bytes")

        meeting_dir, _ = phone.import_recording(
            src, root=crm, transcribe=False, title="Cell C meeting")
        meeting = store.load_meeting(meeting_dir)
        assert meeting.title == "Cell C meeting"
        assert meeting.participants == []
        assert store.list_contacts(root=crm) == []

    def test_the_directory_takes_the_recording_date_not_today(self, crm, fake_ffmpeg,
                                                              monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Eitan new bus.m4a"
        src.write_bytes(b"audio bytes")

        meeting_dir, _ = phone.import_recording(
            src, root=crm, transcribe=False,
            title="Eitan new business",
            when=datetime(2026, 7, 7, 9, 39, 44, tzinfo=SAST),
        )
        assert meeting_dir.name == "2026-07-07-eitan-new-business"

    def test_with_no_overrides_the_filename_still_decides(self, crm, fake_ffmpeg,
                                                          monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Call recording Monty Smythe_260904_143012.m4a"
        src.write_bytes(b"audio bytes")

        meeting_dir, _ = phone.import_recording(src, root=crm, transcribe=False)
        meeting = store.load_meeting(meeting_dir)
        assert meeting.title == "Call with Monty Smythe"
        assert meeting.started_at.startswith("2026-09-04T14:30:12")
        assert meeting_dir.name == "2026-09-04-call-with-monty-smythe"
        assert "monty-smythe" in store.list_contacts(root=crm)

    def test_folder_import_passes_the_overrides_through(self, crm, fake_ffmpeg,
                                                        monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Sameer.m4a"
        src.write_bytes(b"audio bytes")

        result = phone.import_folder(
            src, root=crm, transcribe=False, title="Sameer",
            when=datetime(2026, 7, 30, 10, 9, 42, tzinfo=SAST))
        assert result["imported"] == 1
        assert result["meetings"][0]["name"] == "2026-07-30-sameer"

    def test_overrides_are_refused_for_more_than_one_recording(self, crm, fake_ffmpeg,
                                                               monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        folder = crm / "Call"
        folder.mkdir()
        (folder / "a.m4a").write_bytes(b"a")
        (folder / "b.m4a").write_bytes(b"b")
        with pytest.raises(phone.PhoneImportError, match="one recording"):
            phone.import_folder(folder, root=crm, transcribe=False, title="Both of them")


class TestPhoneCommand:
    def test_a_single_file_with_a_title_and_a_time(self, crm, fake_ffmpeg, monkeypatch):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Discovery-1.m4a"
        src.write_bytes(b"audio bytes")

        code = cli.main(["phone", str(src), "--no-transcribe",
                         "--title", "Discovery 1",
                         "--when", "2026-08-27T10:37:16+02:00"])
        assert code == cli.OK
        assert (crm / "meetings" / "2026-08-27-discovery-1" / "meeting.json").exists()

    def test_a_title_for_a_whole_folder_is_a_user_error(self, crm, fake_ffmpeg,
                                                        monkeypatch, capsys):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        folder = crm / "Call"
        folder.mkdir()
        (folder / "a.m4a").write_bytes(b"a")
        (folder / "b.m4a").write_bytes(b"b")

        code = cli.main(["phone", str(folder), "--no-transcribe", "--title", "One title"])
        assert code == cli.USER_ERROR
        assert "one recording" in capsys.readouterr().err
        assert list((crm / "meetings").glob("*/")) == []

    def test_a_when_that_is_not_a_timestamp_is_a_user_error(self, crm, fake_ffmpeg,
                                                            monkeypatch, capsys):
        monkeypatch.setattr(store, "repo_root", lambda: crm)
        src = crm / "Discovery-1.m4a"
        src.write_bytes(b"audio bytes")

        code = cli.main(["phone", str(src), "--no-transcribe", "--when", "last Tuesday"])
        assert code == cli.USER_ERROR
        assert "last Tuesday" in capsys.readouterr().err


class TestFfmpegMissing:
    def test_error_names_the_install_command(self, tmp_path, monkeypatch):
        monkeypatch.setattr(phone.shutil, "which", lambda n: None)
        with pytest.raises(phone.PhoneImportError, match="winget install"):
            phone.to_wav(tmp_path / "a.m4a", tmp_path / "a.wav")
