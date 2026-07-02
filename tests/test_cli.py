import json

import pytest

import argparse

import requests

from new_ebooks.cli import (
    _fetch_with_auth,
    _parse_retention,
    _provider_tools,
    _prune_result_files,
    _require_macos,
    _result_file_path,
    _retention_label,
    _slugify,
    cmd_check,
    cmd_config,
)
from new_ebooks.config import Config, LibraryConfig, load_config, save_config
from new_ebooks.cookies import cookie_dict
from new_ebooks.scraper import parse_page
from new_ebooks.state import EBookState, LibraryState, State, load_state, save_state

CL_CONFIG = LibraryConfig(
    name="CloudLibrary Test",
    library_base_url="https://ebook.yourcloudlibrary.com/library/scpl",
    formats=["ebook"],
    provider="cloudlibrary",
)

AUTHED_JSON = json.dumps({"results": {"search": {"items": []}}})
LOGIN_PAGE = "<html><title>Sign in</title></html>"


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    """Stands in for requests.Session; returns queued responses."""

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.cookies = {}

    def get(self, url, timeout=None, headers=None) -> FakeResponse:
        return FakeResponse(self.texts.pop(0) if len(self.texts) > 1 else self.texts[0])


def test_fetcher_returns_authenticated_page():
    session = FakeSession([AUTHED_JSON])
    fetcher = _fetch_with_auth(session, CL_CONFIG, LibraryState())
    assert fetcher("https://example.com/search") == AUTHED_JSON


def test_fetcher_reauthenticates_then_succeeds():
    # First fetch: login page; init_session fetch; refetch: authenticated
    session = FakeSession([LOGIN_PAGE, "<html>home</html>", AUTHED_JSON])
    lib_state = LibraryState()
    fetcher = _fetch_with_auth(session, CL_CONFIG, lib_state)
    assert fetcher("https://example.com/search") == AUTHED_JSON


def test_fetcher_raises_when_reauth_does_not_restore_access():
    """An expired session must raise, not be misread downstream as 'no new books'."""
    session = FakeSession([LOGIN_PAGE])
    fetcher = _fetch_with_auth(session, CL_CONFIG, LibraryState())
    with pytest.raises(RuntimeError, match="re-authentication did not restore access"):
        fetcher("https://example.com/search")


def test_slugify():
    assert _slugify("Seattle Public Library") == "seattle-public-library"
    assert _slugify("A/B: C!") == "a-b-c"
    assert _slugify("") == "library"


def test_result_file_path_is_unique(tmp_path):
    results = tmp_path / "results"
    p1 = _result_file_path(results, "Lib")
    p1.write_text("x")
    p2 = _result_file_path(results, "Lib")
    assert p1 != p2
    assert p1.parent == results and results.is_dir()
    assert p1.name.startswith("new_ebooks_lib_") and p1.suffix == ".html"


def test_prune_result_files_keeps_newest(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    made = []
    for i in range(5):
        f = results / f"new_ebooks_lib_2026010{i}.html"
        f.write_text("x")
        # Stagger mtimes so ordering is deterministic.
        import os
        os.utime(f, (1000 + i, 1000 + i))
        made.append(f)

    _prune_result_files(results, 2)
    remaining = sorted(p.name for p in results.glob("new_ebooks_*.html"))
    assert remaining == [made[3].name, made[4].name]


def test_prune_result_files_disabled_when_zero(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    for i in range(3):
        (results / f"new_ebooks_lib_{i}.html").write_text("x")
    _prune_result_files(results, 0)
    assert len(list(results.glob("new_ebooks_*.html"))) == 3


def test_parse_retention():
    assert _parse_retention("", 10) == 10  # blank keeps current
    assert _parse_retention("  ", 10) == 10
    assert _parse_retention("3", 10) == 3
    assert _parse_retention("0", 10) == 0
    assert _parse_retention("-1", 10) == -1
    assert _parse_retention("abc", 10) is None  # non-numeric rejected


def test_retention_label():
    assert _retention_label(5) == "5"
    assert _retention_label(0) == "0 (disabled)"
    assert _retention_label(-1) == "-1 (disabled)"


def test_cmd_config_flags_set_values(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    args = argparse.Namespace(
        config=str(config_path), max_state_backups=7, max_result_files=3
    )
    assert cmd_config(args) == 0
    saved = load_config(config_path)
    assert saved.max_state_backups == 7
    assert saved.max_result_files == 3


def test_cmd_config_flags_partial_keeps_other(tmp_path):
    config_path = tmp_path / "config.json"
    cmd_config(argparse.Namespace(
        config=str(config_path), max_state_backups=7, max_result_files=3
    ))
    # Only set one flag; the other must retain its saved value.
    cmd_config(argparse.Namespace(
        config=str(config_path), max_state_backups=None, max_result_files=1
    ))
    saved = load_config(config_path)
    assert saved.max_state_backups == 7
    assert saved.max_result_files == 1


def test_cmd_config_interactive(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    answers = iter(["2", ""])  # set backups to 2, keep result files default
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    args = argparse.Namespace(
        config=str(config_path), max_state_backups=None, max_result_files=None
    )
    assert cmd_config(args) == 0
    saved = load_config(config_path)
    assert saved.max_state_backups == 2
    assert saved.max_result_files == 10  # default kept


def test_cmd_config_interactive_rejects_non_numeric(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("builtins.input", lambda _: "nope")
    args = argparse.Namespace(
        config=str(config_path), max_state_backups=None, max_result_files=None
    )
    assert cmd_config(args) == 1


def test_require_macos(monkeypatch):
    monkeypatch.setattr("new_ebooks.cli.sys.platform", "darwin")
    assert _require_macos() is True
    monkeypatch.setattr("new_ebooks.cli.sys.platform", "linux")
    assert _require_macos() is False


def test_provider_tools_overdrive():
    config = LibraryConfig(name="L", library_base_url="https://spl.overdrive.com")
    url_builder, page_parser = _provider_tools(config)
    # Default (language unset) preserves the no-filter behavior.
    url = url_builder("https://spl.overdrive.com", "ebook-kindle", 1)
    assert "language=" not in url
    assert page_parser is parse_page


def test_provider_tools_overdrive_language_english():
    config = LibraryConfig(
        name="L", library_base_url="https://spl.overdrive.com", language="english"
    )
    url_builder, _ = _provider_tools(config)
    url = url_builder("https://spl.overdrive.com", "ebook-kindle", 1)
    assert url.endswith("&language=en")


def test_provider_tools_cloudlibrary_language_all():
    config = LibraryConfig(
        name="L", library_base_url=CL_CONFIG.library_base_url,
        formats=["ebook"], provider="cloudlibrary", language="all",
    )
    url_builder, _ = _provider_tools(config)
    url = url_builder(CL_CONFIG.library_base_url, "ebook", 1)
    assert "language=" not in url


def test_provider_tools_cloudlibrary():
    url_builder, page_parser = _provider_tools(CL_CONFIG)
    url = url_builder(CL_CONFIG.library_base_url, "ebook", 2)
    assert "segment=2" in url
    assert "format=digital" in url  # "ebook" config token maps to "digital"
    books = page_parser(json.dumps({"results": {"search": {"items": [
        {"id": "a1", "title": "T", "authors": ["A"]},
    ]}}}))
    assert len(books) == 1
    assert books[0].detail_url == f"{CL_CONFIG.library_base_url}/detail/a1"


def test_cookie_dict_survives_cross_domain_name_conflicts():
    """dict(jar) raises CookieConflictError when the same cookie name exists
    for two domains; the cookie_dict helper must not."""
    jar = requests.cookies.RequestsCookieJar()
    jar.set("sid", "1", domain="a.example.com", path="/")
    jar.set("sid", "2", domain="b.example.com", path="/")
    with pytest.raises(requests.cookies.CookieConflictError):
        dict(jar)  # the failure mode cookie_dict exists to avoid
    snapshot = cookie_dict(jar)
    assert snapshot["sid"] in ("1", "2")


# --- cmd_check end-to-end (network replaced by a fake fetcher) ---

OD_URL = "https://lib.overdrive.com"
OD_FMT = "ebook-epub-adobe"


def _page_html(books: list[tuple[str, str]]) -> str:
    """An Overdrive-style page whose titleCollection lists (id, title) in order."""
    items = [
        {"id": i, "reserveId": f"r{i}", "title": t, "firstCreatorName": "Author", "covers": {}}
        for i, t in books
    ]
    return f"<html><script>window.OverDrive.titleCollection = {json.dumps(items)};</script></html>"


def _check_env(tmp_path, pages: dict[int, str], anchor_id: str | None = "b1"):
    """Write config/state files and return (args, config_path, state_path)."""
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    save_config(Config(libraries=[
        LibraryConfig(name="Lib", library_base_url=OD_URL, formats=[OD_FMT],
                      request_delay_seconds=0.0),
    ]), config_path)
    anchors = {}
    if anchor_id:
        anchors[OD_FMT] = EBookState(anchor_id, f"r{anchor_id}", "Anchor Book", "Author")
    save_state(State(libraries={OD_URL: LibraryState(anchors=anchors)}), state_path, 0)
    return argparse.Namespace(
        config=str(config_path), state=str(state_path), verbose=False,
        library=None, no_open=True, email=False, open=False,
    ), config_path, state_path


def _fake_fetch(pages: dict[int, str]):
    """A _fetch_with_auth stand-in serving canned pages by page number."""
    import re

    def fake(session, lib_config, lib_state, delay=0.0):
        def fetcher(url: str) -> str:
            page = int(re.search(r"page=(\d+)", url).group(1))
            return pages.get(page, _page_html([]))
        return fetcher
    return fake


def test_cmd_check_new_books_writes_results_and_advances_anchor(tmp_path, monkeypatch, capsys):
    pages = {1: _page_html([("b2", "New Book"), ("b1", "Anchor Book")])}
    args, config_path, state_path = _check_env(tmp_path, pages)
    monkeypatch.setattr("new_ebooks.cli._fetch_with_auth", _fake_fetch(pages))

    assert cmd_check(args) == 0

    results = list((tmp_path / "results").glob("new_ebooks_lib_*.html"))
    assert len(results) == 1
    html = results[0].read_text()
    assert "New Book" in html and "Warning" not in html

    state = load_state(state_path)
    lib_state = state.libraries[OD_URL]
    assert lib_state.anchors[OD_FMT].overdrive_id == "b2"
    assert lib_state.last_checked is not None
    assert "1 new" in capsys.readouterr().out


def test_cmd_check_no_new_books_writes_nothing(tmp_path, monkeypatch, capsys):
    pages = {1: _page_html([("b1", "Anchor Book"), ("b0", "Older Book")])}
    args, _, state_path = _check_env(tmp_path, pages)
    monkeypatch.setattr("new_ebooks.cli._fetch_with_auth", _fake_fetch(pages))

    assert cmd_check(args) == 0
    assert not (tmp_path / "results").exists()
    # Anchor unchanged.
    assert load_state(state_path).libraries[OD_URL].anchors[OD_FMT].overdrive_id == "b1"
    assert "no new titles" in capsys.readouterr().out


def test_cmd_check_missing_anchor_renders_warning(tmp_path, monkeypatch, capsys):
    # The anchor never appears; page 2 is empty, so the listing runs out.
    pages = {1: _page_html([("b2", "New Book")])}
    args, _, state_path = _check_env(tmp_path, pages)
    monkeypatch.setattr("new_ebooks.cli._fetch_with_auth", _fake_fetch(pages))

    assert cmd_check(args) == 0
    results = list((tmp_path / "results").glob("new_ebooks_lib_*.html"))
    assert len(results) == 1
    assert "Warning" in results[0].read_text()
    # The anchor still advances so the next run self-heals.
    assert load_state(state_path).libraries[OD_URL].anchors[OD_FMT].overdrive_id == "b2"
    assert "WARNING" in capsys.readouterr().err


def test_cmd_check_first_run_initializes_anchor_without_results(tmp_path, monkeypatch, capsys):
    pages = {1: _page_html([("b2", "Newest Book"), ("b1", "Older Book")])}
    args, _, state_path = _check_env(tmp_path, pages, anchor_id=None)
    monkeypatch.setattr("new_ebooks.cli._fetch_with_auth", _fake_fetch(pages))

    assert cmd_check(args) == 0
    assert not (tmp_path / "results").exists()  # nothing to present yet
    assert load_state(state_path).libraries[OD_URL].anchors[OD_FMT].overdrive_id == "b2"
    assert "initialized" in capsys.readouterr().out
