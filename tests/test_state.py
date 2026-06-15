import json
import time
from pathlib import Path
from new_ebooks.state import State, LibraryState, EBookState, save_state, load_state


def _write_state(path: Path) -> None:
    save_state(State(), path, max_backups=0)  # max_backups=0 skips backup logic


def test_backup_created_on_save(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    time.sleep(0.01)  # ensure mtime differs
    save_state(State(), state_path, max_backups=10)
    backups = list(tmp_path.glob("state.json.*"))
    assert len(backups) == 1


def test_no_duplicate_backup_same_mtime(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    save_state(State(), state_path, max_backups=10)
    save_state(State(), state_path, max_backups=10)
    backups = list(tmp_path.glob("state.json.*"))
    assert len(backups) == 1


def test_old_backups_pruned(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    # Create 5 saves with distinct mtimes
    for _ in range(5):
        time.sleep(0.02)
        save_state(State(), state_path, max_backups=3)
    backups = list(tmp_path.glob("state.json.*"))
    assert len(backups) <= 3


def test_max_backups_zero_skips_backup(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    save_state(State(), state_path, max_backups=0)
    backups = list(tmp_path.glob("state.json.*"))
    assert len(backups) == 0


def test_backup_filenames_are_numeric_timestamps(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    time.sleep(0.01)
    save_state(State(), state_path, max_backups=10)
    backups = list(tmp_path.glob("state.json.*"))
    assert all(b.suffix.lstrip(".").isdigit() for b in backups)


def test_save_leaves_no_temp_file_and_restricts_permissions(tmp_path):
    state_path = tmp_path / "state.json"
    save_state(State(), state_path, max_backups=0)
    assert state_path.exists()
    assert not (tmp_path / "state.json.tmp").exists()
    # State holds session cookies — must be private
    assert (state_path.stat().st_mode & 0o777) == 0o600


def test_state_roundtrip_after_backup(tmp_path):
    state_path = tmp_path / "state.json"
    original = State(libraries={"https://example.com": LibraryState(last_checked="2026-01-01")})
    save_state(original, state_path, max_backups=0)
    time.sleep(0.01)
    save_state(State(), state_path, max_backups=10)
    loaded = load_state(state_path)
    assert loaded is not None
    assert loaded.libraries == {}


def test_anchors_round_trip(tmp_path):
    state_path = tmp_path / "state.json"
    original = State(libraries={"https://x.com": LibraryState(
        anchors={
            "ebook-kindle": EBookState("1", "r1", "Title One", "Author One"),
            "audiobook": EBookState("2", "r2", "Title Two", "Author Two"),
        },
        last_checked="2026-01-01",
    )})
    save_state(original, state_path, max_backups=0)
    loaded = load_state(state_path)
    lib = loaded.libraries["https://x.com"]
    assert lib.anchors["ebook-kindle"].overdrive_id == "1"
    assert lib.anchors["audiobook"].title == "Title Two"


def test_legacy_anchor_migrates_to_transient(tmp_path):
    """An old state file's single most_recent_ebook loads as legacy_anchor."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"libraries": {"https://x.com": {
        "most_recent_ebook": {
            "overdrive_id": "9", "reserve_id": "r9",
            "title": "Old Anchor", "first_creator_name": "Auth",
        },
        "last_checked": "2026-01-01",
        "session_cookies": {},
    }}}))
    loaded = load_state(state_path)
    lib = loaded.libraries["https://x.com"]
    assert lib.anchors == {}
    assert lib.legacy_anchor is not None
    assert lib.legacy_anchor.overdrive_id == "9"


def test_legacy_anchor_not_written_back(tmp_path):
    """The transient legacy anchor is never serialized; only anchors are."""
    state_path = tmp_path / "state.json"
    original = State(libraries={"https://x.com": LibraryState(
        legacy_anchor=EBookState("9", "r9", "Old Anchor", "Auth"),
    )})
    save_state(original, state_path, max_backups=0)
    entry = json.loads(state_path.read_text())["libraries"]["https://x.com"]
    assert "most_recent_ebook" not in entry
    assert entry["anchors"] == {}
