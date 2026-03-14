import time
from pathlib import Path
from new_ebooks.state import State, LibraryState, save_state, load_state


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


def test_state_roundtrip_after_backup(tmp_path):
    state_path = tmp_path / "state.json"
    original = State(libraries={"https://example.com": LibraryState(last_checked="2026-01-01")})
    save_state(original, state_path, max_backups=0)
    time.sleep(0.01)
    save_state(State(), state_path, max_backups=10)
    loaded = load_state(state_path)
    assert loaded is not None
    assert loaded.libraries == {}
