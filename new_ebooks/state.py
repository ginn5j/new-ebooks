from __future__ import annotations
import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

DEFAULT_STATE_PATH = Path.home() / ".config" / "new_ebooks" / "state.json"

# Anchors are keyed by format string. CloudLibrary's legacy "digital"/"audio"
# format values were standardized to "ebook"/"audiobook"; migrate the matching
# anchor keys on load. These tokens are CloudLibrary-only, so the rename is safe
# to apply unconditionally (state has no provider context here).
_ANCHOR_KEY_MIGRATION = {"digital": "ebook", "audio": "audiobook"}


@dataclass
class EBookState:
    overdrive_id: str
    reserve_id: str
    title: str
    first_creator_name: str


@dataclass
class LibraryState:
    # Anchor ("most recent" item) per format, keyed by the format string.
    anchors: dict[str, EBookState] = field(default_factory=dict)
    last_checked: Optional[str] = None
    session_cookies: dict = field(default_factory=dict)
    # Transient: a pre-multi-format anchor read from an old state file. It is
    # never written back; the CLI consumes it into ``anchors`` for the
    # library's primary format on the next save. See load_state.
    legacy_anchor: Optional[EBookState] = None


@dataclass
class State:
    libraries: dict[str, LibraryState] = field(default_factory=dict)


def load_state(path: Path = DEFAULT_STATE_PATH) -> Optional[State]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"State file {path} is not valid JSON ({e}). "
            f"Restore a backup from the same directory ({path.name}.<timestamp>) "
            f"or delete it and run 'new-ebooks reset'."
        )
    libraries = {}
    for url, lib_data in data.get("libraries", {}).items():
        anchors = {
            _ANCHOR_KEY_MIGRATION.get(fmt, fmt): EBookState(**a)
            for fmt, a in (lib_data.get("anchors") or {}).items()
        }
        # Migrate a legacy single-format anchor. State has no access to the
        # config here, so it can't know which format it belongs to; carry it
        # as a transient that the CLI attaches to the primary format.
        legacy_anchor = None
        legacy_data = lib_data.get("most_recent_ebook")
        if legacy_data and not anchors:
            legacy_anchor = EBookState(**legacy_data)
        libraries[url] = LibraryState(
            anchors=anchors,
            last_checked=lib_data.get("last_checked"),
            session_cookies=lib_data.get("session_cookies", {}),
            legacy_anchor=legacy_anchor,
        )
    return State(libraries=libraries)


def _backup_state(path: Path, max_backups: int) -> None:
    if not path.exists() or max_backups <= 0:
        return
    timestamp = int(path.stat().st_mtime)
    backup = path.with_name(f"{path.name}.{timestamp}")
    if not backup.exists():
        shutil.copy2(path, backup)
    # Delete oldest backups until at or below the limit
    backups = sorted(
        p for p in path.parent.glob(f"{path.name}.*")
        if p.suffix.lstrip(".").isdigit()
    )
    while len(backups) > max_backups:
        backups[0].unlink()
        backups = backups[1:]


def save_state(state: State, path: Path = DEFAULT_STATE_PATH, max_backups: int = 10) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup_state(path, max_backups)
    data: dict = {"libraries": {}}
    for url, lib_state in state.libraries.items():
        entry: dict = {
            "last_checked": lib_state.last_checked,
            "session_cookies": lib_state.session_cookies,
            "anchors": {
                fmt: asdict(anchor) for fmt, anchor in lib_state.anchors.items()
            },
        }
        data["libraries"][url] = entry
    # Write atomically: session cookies live here, so keep it private (0600),
    # and a crash mid-write must not corrupt the existing state file.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
