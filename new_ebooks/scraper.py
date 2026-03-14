from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional

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


def build_search_url(base_url: str, format: str, page: int = 1) -> str:
    base_url = base_url.rstrip("/")
    return f"{base_url}/search/title?format={format}&sortBy=newlyadded&page={page}"


def extract_media_items(script_text: str) -> dict:
    pattern = r"window\.OverDrive\.mediaItems\s*=\s*(\{.*?\});"
    match = re.search(pattern, script_text, re.DOTALL)
    if not match:
        return {}
    return json.loads(match.group(1))


def extract_title_collection(script_text: str) -> list[dict]:
    """Extract the raw ordered titleCollection array from a script block."""
    pattern = r"window\.OverDrive\.titleCollection\s*=\s*(\[.*?\]);"
    match = re.search(pattern, script_text, re.DOTALL)
    if not match:
        return []
    return json.loads(match.group(1))


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
