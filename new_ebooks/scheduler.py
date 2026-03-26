from __future__ import annotations
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Optional

PLIST_LABEL = "local.new-ebooks.check"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def write_plist(check_args: list[str], weekday: int, hour: int, minute: int, log_path: Path) -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Capture sys.path at schedule-time so the launchd job gets the exact same
    # module search path that works interactively. This handles editable installs
    # (where .pth files link site-packages → source) and avoids relying on
    # launchd's minimal environment to reconstruct the right path.
    python_path = ":".join(p for p in sys.path if p)

    plist = {
        "Label": PLIST_LABEL,
        "ProgramArguments": [sys.executable, "-m", "new_ebooks", "check"] + check_args,
        "EnvironmentVariables": {"PYTHONPATH": python_path},
        "StartCalendarInterval": {
            "Weekday": weekday,
            "Hour": hour,
            "Minute": minute,
        },
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f)


def _gui_target() -> str:
    return f"gui/{os.getuid()}"


def load_plist() -> None:
    subprocess.run(
        ["launchctl", "bootstrap", _gui_target(), str(PLIST_PATH)],
        check=True, capture_output=True, text=True,
    )


def unload_plist() -> None:
    subprocess.run(
        ["launchctl", "bootout", _gui_target(), str(PLIST_PATH)],
        capture_output=True, text=True,  # don't raise — may not be loaded
    )


def is_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "list", PLIST_LABEL],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def get_schedule_info() -> Optional[dict]:
    if not PLIST_PATH.exists():
        return None
    with open(PLIST_PATH, "rb") as f:
        plist = plistlib.load(f)
    interval = plist.get("StartCalendarInterval", {})
    prog_args = plist.get("ProgramArguments", [])
    # Support both formats:
    #   new: [python, -m, new_ebooks, check, ...args]
    #   old: [script, check, ...args]
    if len(prog_args) >= 4 and prog_args[1:3] == ["-m", "new_ebooks"]:
        check_args = prog_args[4:]
    else:
        check_args = prog_args[2:] if len(prog_args) > 2 else []
    return {
        "weekday": interval.get("Weekday", 0),
        "hour": interval.get("Hour", 0),
        "minute": interval.get("Minute", 0),
        "check_args": check_args,
        "loaded": is_loaded(),
    }
