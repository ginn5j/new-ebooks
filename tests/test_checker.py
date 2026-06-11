import pytest
from new_ebooks.checker import check_for_new_ebooks, find_anchor, MAX_PAGES
from new_ebooks.config import LibraryConfig
from new_ebooks.scraper import EBook
from new_ebooks.state import LibraryState, EBookState

LIB_CONFIG = LibraryConfig(
    name="Test Library",
    library_base_url="https://test.overdrive.com",
    format="ebook-kindle",
    request_delay_seconds=0.0,
)

def make_book(id_: str, title: str) -> EBook:
    return EBook(overdrive_id=id_, reserve_id=f"r{id_}", title=title, first_creator_name="Author")

PAGE1 = [make_book("3", "Newest"), make_book("2", "Middle"), make_book("1", "Oldest")]
PAGE2 = [make_book("0", "Ancient"), make_book("anchor", "The Anchor")]


def test_find_anchor_found():
    assert find_anchor(PAGE1, "2") == 1


def test_find_anchor_not_found():
    assert find_anchor(PAGE1, "99") is None


def test_first_run_no_state():
    """First run with no state: return empty list, set anchor to first book."""
    calls = []
    def fetcher(url: str) -> str:
        calls.append(url)
        from pathlib import Path
        return (Path(__file__).parent / "fixtures" / "sample_page.html").read_text()

    new_books, anchor = check_for_new_ebooks(LIB_CONFIG, None, fetcher)
    assert new_books == []
    assert anchor is not None
    # Fixture titleCollection order is: 87654321, 11111111, 12345678
    assert anchor.overdrive_id == "87654321"
    assert len(calls) == 1  # only fetched one page


def test_no_new_books():
    """Anchor is first book in display order: no new books."""
    lib_state = LibraryState(
        most_recent_ebook=EBookState("87654321", "r2", "Recursive Dreams", "Brian Stack")
    )
    def fetcher(url: str) -> str:
        from pathlib import Path
        return (Path(__file__).parent / "fixtures" / "sample_page.html").read_text()

    new_books, anchor = check_for_new_ebooks(LIB_CONFIG, lib_state, fetcher)
    assert new_books == []
    assert anchor is None


def test_some_new_books():
    """Anchor is second book in display order: first book is new."""
    lib_state = LibraryState(
        most_recent_ebook=EBookState("11111111", "r3", "Old Book", "Carl Legacy")
    )
    def fetcher(url: str) -> str:
        from pathlib import Path
        return (Path(__file__).parent / "fixtures" / "sample_page.html").read_text()

    new_books, anchor = check_for_new_ebooks(LIB_CONFIG, lib_state, fetcher)
    assert len(new_books) == 1
    assert new_books[0].overdrive_id == "87654321"
    assert anchor.overdrive_id == "87654321"


def test_multi_page(monkeypatch):
    """Anchor on page 2: all of page 1 + books before anchor on page 2 are new."""
    monkeypatch.setattr("new_ebooks.checker.MAX_PAGES", 5)

    page1_html = _make_html({"101": "Book A", "102": "Book B"})
    page2_html = _make_html({"103": "Book C", "anchor_id": "The Anchor"})

    pages = [page1_html, page2_html]
    call_count = [0]

    def fetcher(url: str) -> str:
        html = pages[call_count[0] % len(pages)]
        call_count[0] += 1
        return html

    lib_state = LibraryState(
        most_recent_ebook=EBookState("anchor_id", "r0", "The Anchor", "Old Author")
    )

    new_books, anchor = check_for_new_ebooks(LIB_CONFIG, lib_state, fetcher)
    assert len(new_books) == 3  # 2 from page1 + 1 from page2 (Book C before anchor)
    assert new_books[0].overdrive_id == "101"
    assert anchor.overdrive_id == "101"


def _make_html(books: dict) -> str:
    """Build a minimal Overdrive-style HTML page from {id: title}."""
    items = []
    for id_, title in books.items():
        items.append(
            f'"{id_}": {{"id": "{id_}", "reserveId": "r{id_}", '
            f'"title": "{title}", "creators": [{{"name": "Author", "role": "Author"}}], "covers": {{}}}}'
        )
    items_json = "{" + ", ".join(items) + "}"
    return f"""<html><body><script>
window.OverDrive = window.OverDrive || {{}};
window.OverDrive.mediaItems = {items_json};
</script></body></html>"""


def test_safety_valve(monkeypatch):
    """If anchor is never found, stop at MAX_PAGES; repeated pages are de-duplicated."""
    monkeypatch.setattr("new_ebooks.checker.MAX_PAGES", 3)

    page_html = _make_html({"new1": "New Book 1", "new2": "New Book 2"})

    def fetcher(url: str) -> str:
        return page_html

    lib_state = LibraryState(
        most_recent_ebook=EBookState("missing_anchor", "r0", "Gone Book", "Author")
    )

    new_books, anchor = check_for_new_ebooks(LIB_CONFIG, lib_state, fetcher)
    # 3 pages of the same 2 books — each book counted once
    assert len(new_books) == 2
    assert [b.overdrive_id for b in new_books] == ["new1", "new2"]


def test_page_shift_duplicates_removed(monkeypatch):
    """A book that shifts from the bottom of page 1 to the top of page 2 appears once."""
    monkeypatch.setattr("new_ebooks.checker.MAX_PAGES", 5)

    page1_html = _make_html({"101": "Book A", "102": "Book B"})
    # "102" repeats at the top of page 2 (list shifted mid-check)
    page2_html = _make_html({"102": "Book B", "103": "Book C", "anchor_id": "The Anchor"})

    pages = [page1_html, page2_html]
    call_count = [0]

    def fetcher(url: str) -> str:
        html = pages[call_count[0]]
        call_count[0] += 1
        return html

    lib_state = LibraryState(
        most_recent_ebook=EBookState("anchor_id", "r0", "The Anchor", "Old Author")
    )

    new_books, anchor = check_for_new_ebooks(LIB_CONFIG, lib_state, fetcher)
    assert [b.overdrive_id for b in new_books] == ["101", "102", "103"]
    assert anchor.overdrive_id == "101"


# --- CloudLibrary-style provider override (url_builder + page_parser) ---

import json as _json

CL_CONFIG = LibraryConfig(
    name="CloudLibrary Test",
    library_base_url="https://ebook.yourcloudlibrary.com/library/scpl",
    format="digital",
    request_delay_seconds=0.0,
    provider="cloudlibrary",
)


def _make_cl_json(books: list[tuple[str, str, str]]) -> str:
    """Build a minimal CloudLibrary JSON response from [(id, title, author), ...]."""
    items = [
        {"id": id_, "title": title, "authors": [author],
         "imageLinkThumbnail": "", "currentlyAvailable": None, "summary": ""}
        for id_, title, author in books
    ]
    return _json.dumps({"results": {"search": {"totalItems": len(items), "items": items}}})


def _cl_url_builder(base_url: str, format: str, page: int = 1) -> str:
    return f"{base_url}/search?segment={page}"


def _cl_page_parser(json_text: str) -> list[EBook]:
    from new_ebooks.cloudlibrary import parse_page
    return parse_page(json_text)


def test_custom_url_builder_is_called():
    """url_builder receives the library base URL, format, and page number."""
    calls = []

    def url_builder(base_url: str, format: str, page: int = 1) -> str:
        calls.append((base_url, format, page))
        return _make_cl_json([("a1", "Book A", "Author A")])  # not a real URL, fetcher ignores it

    def fetcher(url: str) -> str:
        return _make_cl_json([("a1", "Book A", "Author A")])

    lib_state = LibraryState(most_recent_ebook=EBookState("a1", "", "Book A", "Author A"))
    check_for_new_ebooks(CL_CONFIG, lib_state, fetcher, url_builder=url_builder, page_parser=_cl_page_parser)
    assert calls[0] == (CL_CONFIG.library_base_url, CL_CONFIG.format, 1)


def test_custom_page_parser_is_called():
    """page_parser receives the raw response text and its results are used."""
    parsed = []

    def page_parser(text: str) -> list[EBook]:
        books = _cl_page_parser(text)
        parsed.extend(books)
        return books

    page_json = _make_cl_json([("newer", "Newer Book", "Auth"), ("anchor", "Anchor Book", "Auth")])

    def fetcher(url: str) -> str:
        return page_json

    lib_state = LibraryState(most_recent_ebook=EBookState("anchor", "", "Anchor Book", "Auth"))
    new_books, anchor = check_for_new_ebooks(
        CL_CONFIG, lib_state, fetcher,
        url_builder=_cl_url_builder, page_parser=page_parser,
    )
    assert len(new_books) == 1
    assert new_books[0].overdrive_id == "newer"
    assert len(parsed) >= 1


def test_cloudlibrary_first_run():
    """First run with CloudLibrary provider sets anchor, returns no new books."""
    page_json = _make_cl_json([("id1", "First Book", "Author One"), ("id2", "Second Book", "Author Two")])

    def fetcher(url: str) -> str:
        return page_json

    new_books, anchor = check_for_new_ebooks(
        CL_CONFIG, None, fetcher,
        url_builder=_cl_url_builder, page_parser=_cl_page_parser,
    )
    assert new_books == []
    assert anchor is not None
    assert anchor.overdrive_id == "id1"


def test_cloudlibrary_new_books_found():
    """New books before the anchor are returned."""
    page_json = _make_cl_json([
        ("new1", "Brand New", "Auth"),
        ("new2", "Also New", "Auth"),
        ("anchor", "Old Anchor", "Auth"),
    ])

    def fetcher(url: str) -> str:
        return page_json

    lib_state = LibraryState(most_recent_ebook=EBookState("anchor", "", "Old Anchor", "Auth"))
    new_books, anchor = check_for_new_ebooks(
        CL_CONFIG, lib_state, fetcher,
        url_builder=_cl_url_builder, page_parser=_cl_page_parser,
    )
    assert len(new_books) == 2
    assert new_books[0].overdrive_id == "new1"
    assert new_books[1].overdrive_id == "new2"
    assert anchor.overdrive_id == "new1"
