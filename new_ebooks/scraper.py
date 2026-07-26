from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class EBook:
    overdrive_id: str
    reserve_id: str
    title: str
    first_creator_name: str
    cover_url: str = ""
    is_available: bool = False
    description: str = ""
    detail_url: str = ""


def _overdrive_language_value(language: str | None) -> str:
    """Map a neutral language token to Overdrive's URL value.

    None/"all" → no filter (current default); "english" → "en".
    """
    if language == "english":
        return "en"
    return ""


# Overdrive's search distinguishes a specific *format* (format=ebook-epub-adobe)
# from a broader *media type* (mediaType=audiobook). The friendly "audiobook"
# token (matching CloudLibrary's "audio" shorthand and the renderer's media
# kinds) is a media type, not a format: searching with format=audiobook returns
# an empty result set. Map it to the mediaType query parameter instead. Specific
# format identifiers the caller already qualified (e.g. "audiobook-mp3") stay on
# the format parameter.
_MEDIA_TYPES = {"audiobook"}


def build_search_url(
    base_url: str, format: str, page: int = 1, language: str | None = None
) -> str:
    base_url = base_url.rstrip("/")
    if format in _MEDIA_TYPES:
        param = f"mediaType={format}"
    else:
        param = f"format={format}"
    url = f"{base_url}/search/title?{param}&sortBy=newlyadded&page={page}"
    lang_value = _overdrive_language_value(language)
    if lang_value:
        url += f"&language={lang_value}"
    return url


def _extract_json(script_text: str, prefix: str, open_close: str, default):
    # The lazy match stops at the first close+semicolon, which can occur
    # inside a JSON string (e.g. a description containing "};"). If that
    # truncated capture fails to parse, retry greedily.
    o, c = open_close
    for quantifier in ("*?", "*"):
        pattern = rf"{prefix}\s*=\s*(\{o}.{quantifier}\{c});"
        match = re.search(pattern, script_text, re.DOTALL)
        if not match:
            return default
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    return default


def extract_media_items(script_text: str) -> dict:
    return _extract_json(script_text, r"window\.OverDrive\.mediaItems", "{}", {})


def extract_title_collection(script_text: str) -> list[dict]:
    """Extract the raw ordered titleCollection array from a script block."""
    return _extract_json(script_text, r"window\.OverDrive\.titleCollection", "[]", [])


def _cover_url(covers: dict) -> str:
    for key in ("cover150Wide", "cover300Wide", "cover510Wide", "cover"):
        if key in covers and "href" in covers[key]:
            return covers[key]["href"]
    return ""


def _ebook_from_title_collection_item(data: dict) -> EBook:
    return EBook(
        overdrive_id=str(data.get("id", "")),
        reserve_id=str(data.get("reserveId", "")),
        title=data.get("title", ""),
        first_creator_name=data.get("firstCreatorName", ""),
        cover_url=_cover_url(data.get("covers", {})),
        is_available=bool(data.get("isAvailable") or data.get("availableCopies", 0) > 0),
        description=data.get("description", ""),
    )


def _ebook_from_media_item(item_id: str, data: dict) -> EBook:
    creators = data.get("creators", [])
    first_creator = creators[0].get("name", "") if creators else ""
    return EBook(
        overdrive_id=str(data.get("id", item_id)),
        reserve_id=str(data.get("reserveId", "")),
        title=data.get("title", ""),
        first_creator_name=first_creator,
        cover_url=_cover_url(data.get("covers", {})),
    )


def parse_page(html: str) -> list[EBook]:
    soup = BeautifulSoup(html, "html.parser")
    scripts = [tag.string for tag in soup.find_all("script") if tag.string]

    # Prefer titleCollection — it is ordered and contains all needed fields directly
    for script in scripts:
        if "window.OverDrive.titleCollection" in script:
            items = extract_title_collection(script)
            if items:
                return [_ebook_from_title_collection_item(item) for item in items]

    # Fall back to mediaItems (unordered dict)
    for script in scripts:
        if "window.OverDrive.mediaItems" in script:
            media_items = extract_media_items(script)
            return [_ebook_from_media_item(k, v) for k, v in media_items.items()]

    return []
