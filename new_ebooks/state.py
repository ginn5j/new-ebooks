from __future__ import annotations
import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

DEFAULT_STATE_PATH = Path.home() / ".config" / "new_ebooks" / "state.json"


@dataclass
class EBookState:
    overdrive_id: str
    reserve_id: str
    title: str
    first_creator_name: str


@dataclass
class LibraryState:
    most_recent_ebook: Optional[EBookState] = None
    last_checked: Optional[str] = None
    session_cookies: dict = field(default_factory=dict)


@dataclass
class State:
    libraries: dict[str, LibraryState] = field(default_factory=dict)


def load_state(path: Path = DEFAULT_STATE_PATH) -> Optional[State]:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    libraries = {}
    for url, lib_data in data.get("libraries", {}).items():
        mre_data = lib_data.get("most_recent_ebook")
        mre = EBookState(**mre_data) if mre_data else None
        libraries[url] = LibraryState(
            most_recent_ebook=mre,
            last_checked=lib_data.get("last_checked"),
            session_cookies=lib_data.get("session_cookies", {}),
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
        }
        if lib_state.most_recent_ebook:
            entry["most_recent_ebook"] = asdict(lib_state.most_recent_ebook)
        else:
            entry["most_recent_ebook"] = None
        data["libraries"][url] = entry
    path.write_text(json.dumps(data, indent=2))
