import json

import pytest

from new_ebooks.cli import _fetch_with_auth, _provider_tools
from new_ebooks.config import LibraryConfig
from new_ebooks.scraper import build_search_url, parse_page
from new_ebooks.state import LibraryState

CL_CONFIG = LibraryConfig(
    name="CloudLibrary Test",
    library_base_url="https://ebook.yourcloudlibrary.com/library/scpl",
    format="digital",
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
        format="digital", provider="cloudlibrary", language="all",
    )
    url_builder, _ = _provider_tools(config)
    url = url_builder(CL_CONFIG.library_base_url, "digital", 1)
    assert "language=" not in url


def test_provider_tools_cloudlibrary():
    url_builder, page_parser = _provider_tools(CL_CONFIG)
    url = url_builder(CL_CONFIG.library_base_url, "digital", 2)
    assert "segment=2" in url
    books = page_parser(json.dumps({"results": {"search": {"items": [
        {"id": "a1", "title": "T", "authors": ["A"]},
    ]}}}))
    assert len(books) == 1
    assert books[0].detail_url == f"{CL_CONFIG.library_base_url}/detail/a1"
