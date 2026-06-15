from __future__ import annotations
from typing import Callable, Optional

from new_ebooks.config import LibraryConfig
from new_ebooks.scraper import EBook, build_search_url, parse_page
from new_ebooks.state import LibraryState

MAX_PAGES = 50


def find_anchor(books: list[EBook], anchor_id: str) -> Optional[int]:
    for i, book in enumerate(books):
        if book.overdrive_id == anchor_id:
            return i
    return None


def check_for_new_ebooks(
    config: LibraryConfig,
    lib_state: Optional[LibraryState],
    fetcher: Callable[[str], str],
    url_builder: Optional[Callable] = None,
    page_parser: Optional[Callable] = None,
    fmt: Optional[str] = None,
    anchor_id: Optional[str] = None,
) -> tuple[list[EBook], Optional[EBook], bool]:
    """
    Check a single format and return (new_books, new_anchor, anchor_found).
    new_anchor is the book to save as this format's anchor for the next run.
    If this is the first run (no anchor for the format), returns
    ([], first_book, True).

    ``anchor_found`` is False when the stored anchor was never seen in the
    results — either the listing ran out of pages or MAX_PAGES was hit before
    reaching it. In that case ``new_books`` may be a flood of titles the user
    has already seen (the anchor was likely removed from the collection), so
    callers should warn rather than trust the list. It is always True on a
    first run, where there is no anchor to find.

    ``fmt`` defaults to the library's primary (first) format; ``anchor_id``
    defaults to that format's stored anchor.
    """
    if url_builder is None:
        url_builder = build_search_url
    if page_parser is None:
        page_parser = parse_page

    if fmt is None:
        fmt = config.formats[0]

    if anchor_id is None and lib_state:
        anchor = lib_state.anchors.get(fmt)
        if anchor:
            anchor_id = anchor.overdrive_id

    new_books: list[EBook] = []
    new_anchor: Optional[EBook] = None
    seen_ids: set[str] = set()

    def add_new(books: list[EBook]) -> None:
        # Pagination can shift while a check is running (a title added
        # mid-check pushes books from the bottom of one page to the top of
        # the next), so the same book may appear on consecutive pages.
        for book in books:
            if book.overdrive_id not in seen_ids:
                seen_ids.add(book.overdrive_id)
                new_books.append(book)

    anchor_found = False
    for page_num in range(1, MAX_PAGES + 1):
        url = url_builder(config.library_base_url, fmt, page_num)
        html = fetcher(url)
        books = page_parser(html)

        if not books:
            # Ran out of pages without reaching the anchor.
            break

        if anchor_id is None:
            # First run: just record the first book as anchor, collect nothing
            new_anchor = books[0] if books else None
            return [], new_anchor, True

        idx = find_anchor(books, anchor_id)
        if idx is None:
            # Anchor not on this page — all books are new
            add_new(books)
        else:
            # Anchor found — take everything before it
            add_new(books[:idx])
            anchor_found = True
            break

    else:
        # Safety valve: anchor not found after MAX_PAGES
        return new_books, new_books[0] if new_books else None, False

    new_anchor = new_books[0] if new_books else None
    return new_books, new_anchor, anchor_found
