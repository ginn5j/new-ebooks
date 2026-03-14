from __future__ import annotations
import time
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
) -> tuple[list[EBook], Optional[EBook]]:
    """
    Returns (new_books, new_anchor).
    new_anchor is the book to save as most_recent_ebook for next run.
    If this is the first run (lib_state is None or has no anchor), returns ([], first_book).
    """
    anchor_id = None
    if lib_state and lib_state.most_recent_ebook:
        anchor_id = lib_state.most_recent_ebook.overdrive_id

    new_books: list[EBook] = []
    new_anchor: Optional[EBook] = None

    for page_num in range(1, MAX_PAGES + 1):
        url = build_search_url(config.library_base_url, config.format, page_num)
        html = fetcher(url)
        books = parse_page(html)

        if not books:
            break

        if anchor_id is None:
            # First run: just record the first book as anchor, collect nothing
            new_anchor = books[0] if books else None
            return [], new_anchor

        idx = find_anchor(books, anchor_id)
        if idx is None:
            # Anchor not on this page — all books are new
            new_books.extend(books)
        else:
            # Anchor found — take everything before it
            new_books.extend(books[:idx])
            break

        if page_num < MAX_PAGES:
            time.sleep(config.request_delay_seconds)
    else:
        # Safety valve: anchor not found after MAX_PAGES
        return new_books, new_books[0] if new_books else None

    new_anchor = new_books[0] if new_books else None
    return new_books, new_anchor
