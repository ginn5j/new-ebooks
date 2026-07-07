import plistlib
import sys

import new_ebooks.scheduler as scheduler


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "PLIST_PATH", tmp_path / "test.plist")
    monkeypatch.setattr(scheduler, "LAUNCHER_PATH", tmp_path / "launcher.py")
    monkeypatch.setattr(scheduler, "PKG_CACHE_DIR", tmp_path / "pkg")
    # launchctl is macOS-only; the loaded flag isn't under test here.
    monkeypatch.setattr(scheduler, "is_loaded", lambda: False)


def _write_manual_plist(monkeypatch, tmp_path, prog_args):
    _patch_paths(monkeypatch, tmp_path)
    plist = {
        "Label": scheduler.PLIST_LABEL,
        "ProgramArguments": prog_args,
        "StartCalendarInterval": {"Weekday": 2, "Hour": 8, "Minute": 15},
    }
    with open(scheduler.PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f)


def test_get_schedule_info_none_without_plist(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    assert scheduler.get_schedule_info() is None


def test_write_plist_round_trips_through_get_schedule_info(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    scheduler.write_plist(["--email"], 1, 9, 30, tmp_path / "check.log")

    info = scheduler.get_schedule_info()
    assert info == {
        "weekday": 1,
        "hour": 9,
        "minute": 30,
        "check_args": ["--email"],
        "loaded": False,
    }


def test_write_plist_writes_launcher_and_package_cache(tmp_path, monkeypatch):
    _patch_paths(monkeypatch, tmp_path)
    scheduler.write_plist(["--no-open"], 0, 7, 0, tmp_path / "check.log")

    launcher = (tmp_path / "launcher.py").read_text()
    assert "from new_ebooks.cli import main" in launcher
    # The cached package copy must be importable ahead of site-packages.
    assert (tmp_path / "pkg" / "new_ebooks" / "cli.py").exists()
    assert launcher.index(str(tmp_path / "pkg")) < launcher.index("main")

    with open(tmp_path / "test.plist", "rb") as f:
        plist = plistlib.load(f)
    assert plist["ProgramArguments"] == [
        "/usr/bin/caffeinate", "-i", "-s",
        sys.executable,
        str(tmp_path / "launcher.py"),
        "--verbose",
        "check",
        "--no-open",
    ]
    assert plist["ProcessType"] == "Interactive"
    assert plist["StandardOutPath"] == str(tmp_path / "check.log")


def test_get_schedule_info_parses_v3_launcher_layout(tmp_path, monkeypatch):
    _write_manual_plist(
        monkeypatch, tmp_path,
        [sys.executable, str(tmp_path / "launcher.py"), "check", "--email"],
    )
    assert scheduler.get_schedule_info()["check_args"] == ["--email"]


def test_get_schedule_info_parses_v2_module_layout(tmp_path, monkeypatch):
    _write_manual_plist(
        monkeypatch, tmp_path,
        [sys.executable, "-m", "new_ebooks", "check", "--email"],
    )
    info = scheduler.get_schedule_info()
    assert info["check_args"] == ["--email"]
    assert (info["weekday"], info["hour"], info["minute"]) == (2, 8, 15)


def test_get_schedule_info_parses_v1_script_layout(tmp_path, monkeypatch):
    _write_manual_plist(
        monkeypatch, tmp_path,
        ["/usr/local/bin/new-ebooks", "check", "--no-open"],
    )
    assert scheduler.get_schedule_info()["check_args"] == ["--no-open"]


def test_get_schedule_info_no_extra_args(tmp_path, monkeypatch):
    _write_manual_plist(
        monkeypatch, tmp_path,
        [sys.executable, str(tmp_path / "launcher.py"), "check"],
    )
    assert scheduler.get_schedule_info()["check_args"] == []
