from __future__ import annotations
import json
from typing import Optional
from urllib.parse import urlencode

import requests

from new_ebooks.scraper import EBook


def _cloudlibrary_language_value(language: Optional[str]) -> str:
    """Map a neutral language token to CloudLibrary's URL value.

    None/"english" → "eng" (current default); "all" → no filter.
    """
    if language == "all":
        return ""
    return "eng"


# The friendly config tokens ("ebook"/"audiobook") match the renderer's media
# kinds and Overdrive's "audiobook" media type. CloudLibrary's search endpoint
# expects different wire values, so map them here. Any value not in the map
# (e.g. a raw "digital"/"audio" that slipped through) passes through unchanged.
_FORMAT_QUERY = {"ebook": "digital", "audiobook": "audio"}


def build_search_url(
    base_url: str, format: str, page: int = 1, language: Optional[str] = None
) -> str:
    base_url = base_url.rstrip("/")
    params = {
        "_data": "routes/library.$name.search",
        "sort": "-dateadded",
        "format": _FORMAT_QUERY.get(format, format),
    }
    lang_value = _cloudlibrary_language_value(language)
    if lang_value:
        params["language"] = lang_value
    params["segment"] = page
    return f"{base_url}/search?{urlencode(params)}"


def parse_page(json_text: str, library_base_url: str = "") -> list[EBook]:
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError):
        return []

    try:
        items = data["results"]["search"]["items"]
    except (KeyError, TypeError):
        return []

    books = []
    for item in items:
        item_id = item.get("id", "")

        authors = item.get("authors") or []
        first_author = authors[0] if authors else ""

        detail_url = f"{library_base_url.rstrip('/')}/detail/{item_id}" if library_base_url else ""

        books.append(EBook(
            overdrive_id=item_id,
            reserve_id="",
            title=item.get("title", ""),
            first_creator_name=first_author,
            cover_url=item.get("imageLinkThumbnail", ""),
            is_available=bool(item.get("currentlyAvailable")),
            description=item.get("summary", ""),
            detail_url=detail_url,
        ))

    return books


def is_authenticated(response_text: str) -> bool:
    try:
        data = json.loads(response_text)
        return "results" in data or "categories" in data
    except (json.JSONDecodeError, ValueError):
        return False


def init_session(session: requests.Session, library_base_url: str) -> dict:
    resp = session.get(library_base_url.rstrip("/"), timeout=15)
    resp.raise_for_status()
    return dict(session.cookies)
