from __future__ import annotations
import html as html_mod
import re
import webbrowser
from datetime import datetime
from pathlib import Path

from new_ebooks.scraper import EBook

_ALL_TAGS_RE = re.compile(r'<[^>]+>')

# Media kinds, in the order sections are presented. Each kind carries the
# nouns and the in-page anchor id used for navigation links.
KIND_ORDER = ["ebook", "audiobook"]
KIND_META = {
    "ebook": {"noun": "eBook", "id": "ebooks", "nav": "eBooks"},
    "audiobook": {"noun": "audiobook", "id": "audiobooks", "nav": "audiobooks"},
}


def media_kind(fmt: str) -> str:
    """Map a provider format string to a media kind ('ebook' or 'audiobook')."""
    return "audiobook" if fmt in ("audiobook", "audio") else "ebook"


def _escape(text: str) -> str:
    return html_mod.escape(text, quote=True)


def _sanitize_description(html: str) -> str:
    """Strip all HTML tags and return plain text, HTML-escaped for safe insertion."""
    text = _ALL_TAGS_RE.sub(" ", html)
    text = re.sub(r" {2,}", " ", text).strip()
    return _escape(text)


def format_date(iso_timestamp: str) -> str:
    """Format an ISO timestamp for display (e.g. 'Jun 11, 2026'); pass through anything unparseable."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
    except (ValueError, TypeError):
        return iso_timestamp
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def _plural(noun: str, count: int) -> str:
    return noun if count == 1 else f"{noun}s"


def build_heading(count: int, last_checked: str, library_name: str = "", noun: str = "eBook") -> str:
    """Build the 'N new <noun>s since X — Lib' string used for headings and subjects."""
    if count == 0:
        heading = f"No new {noun}s"
    else:
        heading = f"{count} new {_plural(noun, count)}"
    if last_checked:
        heading += f" since {format_date(last_checked)}"
    if library_name:
        heading += f" — {library_name}"
    return heading


def _as_sections(sections) -> list[tuple[str, list[EBook]]]:
    """Accept either a flat ``list[EBook]`` or ``(format, books)`` tuples.

    A flat list is treated as a single eBook section, so callers that don't
    care about format grouping can keep passing a plain book list.
    """
    if sections and isinstance(sections[0], EBook):
        return [("ebook", list(sections))]
    return list(sections)


def group_sections(sections: list[tuple[str, list[EBook]]]) -> list[tuple[str, list[EBook]]]:
    """Merge (format, books) pairs into ordered (kind, books) groups.

    Books are grouped by media kind (so two eBook formats land in one
    section), de-duplicated by id within a kind, and empty groups dropped.
    """
    buckets: dict[str, tuple[list[EBook], set[str]]] = {}
    for fmt, books in _as_sections(sections):
        kind = media_kind(fmt)
        bucket, seen = buckets.setdefault(kind, ([], set()))
        for book in books:
            if book.overdrive_id not in seen:
                seen.add(book.overdrive_id)
                bucket.append(book)
    return [
        (kind, buckets[kind][0])
        for kind in KIND_ORDER
        if kind in buckets and buckets[kind][0]
    ]


def page_heading(sections: list[tuple[str, list[EBook]]], last_checked: str, library_name: str = "") -> str:
    """Top-level heading / email subject covering all sections for a library."""
    groups = group_sections(sections)
    total = sum(len(books) for _, books in groups)
    # Distinct kinds present in the input (even ones with zero new books) pick
    # the noun, so a single-format library still reads "No new eBooks".
    kinds: list[str] = []
    for fmt, _ in _as_sections(sections):
        kind = media_kind(fmt)
        if kind not in kinds:
            kinds.append(kind)
    if len(kinds) <= 1:
        noun = KIND_META[kinds[0]]["noun"] if kinds else "eBook"
        return build_heading(total, last_checked, library_name, noun=noun)
    return build_heading(total, last_checked, library_name, noun="title")


PLACEHOLDER_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='150' height='200' "
    "viewBox='0 0 150 200'%3E%3Crect width='150' height='200' fill='%23ddd'/%3E"
    "%3Ctext x='75' y='110' font-size='14' text-anchor='middle' fill='%23999'%3ENo Cover%3C/text%3E%3C/svg%3E"
)

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #f5f5f5; color: #222; padding: 1.5rem; }
h1 { font-size: 1.5rem; margin-bottom: 1rem; color: #333; }
h2 { font-size: 1.15rem; margin: 1.5rem 0 0.75rem; color: #333; scroll-margin-top: 3rem; }
.nav { position: sticky; top: 0; background: #f5f5f5; padding: 0.5rem 0; margin-bottom: 0.5rem; font-size: 0.85rem; }
.nav a { color: #1a56c4; text-decoration: none; margin-right: 1rem; }
.nav a:hover { text-decoration: underline; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; align-items: start; }
.book-card {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.12);
  width: 220px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.book-card img {
  width: 100%;
  height: 200px;
  object-fit: contain;
  background: #eee;
}
.book-info {
  padding: 0.6rem;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.book-info strong { font-size: 0.85rem; line-height: 1.3; }
.book-info .author { font-size: 0.78rem; color: #666; }
.book-info .description {
  font-size: 0.75rem;
  color: #444;
  line-height: 1.4;
  margin-top: 0.35rem;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.book-link {
  display: block;
  margin: 0.5rem 0.6rem 0.6rem;
  padding: 0.35rem 0;
  border-radius: 4px;
  text-align: center;
  text-decoration: none;
  font-size: 0.78rem;
  font-weight: 600;
}
.book-link.borrow { background: #1a7f4b; color: #fff; }
.book-link.hold { background: #e8f0fe; color: #1a56c4; }
"""


def _card_html(book: EBook, library_base_url: str) -> str:
    src = _escape(book.cover_url) if book.cover_url else PLACEHOLDER_SVG
    title_escaped = _escape(book.title)
    author_escaped = _escape(book.first_creator_name)
    if library_base_url or book.detail_url:
        detail_url = _escape(book.detail_url or f"{library_base_url.rstrip('/')}/media/{book.overdrive_id}")
        if book.is_available:
            link = f'<a class="book-link borrow" href="{detail_url}" target="_blank">Borrow</a>'
        else:
            link = f'<a class="book-link hold" href="{detail_url}" target="_blank">Place a Hold</a>'
    else:
        link = ""
    description = f'<div class="description">{_sanitize_description(book.description)}</div>' if book.description else ""
    return (
        f'<div class="book-card">'
        f'<img src="{src}" alt="Cover" onerror="this.src=\'{PLACEHOLDER_SVG}\'">'
        f'<div class="book-info">'
        f"<strong>{title_escaped}</strong>"
        f'<span class="author">{author_escaped}</span>'
        f"{description}"
        f"</div>"
        f"{link}"
        f"</div>"
    )


def _nav_html(groups: list[tuple[str, list[EBook]]]) -> str:
    """Build the in-page navigation bar. Empty when there is only one section."""
    if len(groups) < 2:
        return ""
    links = ['<a href="#top">Go to top</a>']
    for kind, _ in groups:
        meta = KIND_META[kind]
        links.append(f'<a href="#{meta["id"]}">Go to {meta["nav"]}</a>')
    return f'<div class="nav">{"".join(links)}</div>'


def render_html(sections: list[tuple[str, list[EBook]]], last_checked: str, library_name: str = "", library_base_url: str = "") -> str:
    groups = group_sections(sections)
    heading = page_heading(sections, last_checked, library_name)
    heading_escaped = _escape(heading)
    nav = _nav_html(groups)

    body_parts = []
    for kind, books in groups:
        meta = KIND_META[kind]
        section_heading = _escape(build_heading(len(books), "", "", noun=meta["noun"]))
        cards = "\n".join(_card_html(book, library_base_url) for book in books)
        body_parts.append(
            f'<h2 id="{meta["id"]}">{section_heading}</h2>\n'
            f'<div class="grid">\n{cards}\n</div>'
        )
    body_html = "\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading_escaped}</title>
<style>{CSS}</style>
</head>
<body id="top">
<h1>{heading_escaped}</h1>
{nav}
{body_html}
</body>
</html>"""


def _email_card_html(book: EBook, library_base_url: str) -> str:
    src = _escape(book.cover_url) if book.cover_url else ""
    title_escaped = _escape(book.title)
    author_escaped = _escape(book.first_creator_name)
    cover_html = (
        f'<img src="{src}" alt="Cover" width="150" height="200" '
        f'style="width:150px;height:200px;object-fit:contain;background:#eee;display:block;">'
        if src else
        '<div style="width:150px;height:200px;background:#ddd;display:flex;align-items:center;'
        'justify-content:center;color:#999;font-size:13px;">No Cover</div>'
    )
    if library_base_url or book.detail_url:
        detail_url = _escape(book.detail_url or f"{library_base_url.rstrip('/')}/media/{book.overdrive_id}")
        if book.is_available:
            link = (
                f'<a href="{detail_url}" style="display:block;margin:8px 10px;padding:6px 0;'
                f'border-radius:4px;text-align:center;text-decoration:none;font-size:12px;'
                f'font-weight:600;background:#1a7f4b;color:#fff;">Borrow</a>'
            )
        else:
            link = (
                f'<a href="{detail_url}" style="display:block;margin:8px 10px;padding:6px 0;'
                f'border-radius:4px;text-align:center;text-decoration:none;font-size:12px;'
                f'font-weight:600;background:#e8f0fe;color:#1a56c4;">Place a Hold</a>'
            )
    else:
        link = ""
    description_text = _sanitize_description(book.description) if book.description else ""
    description_html = (
        f'<div style="font-size:12px;color:#444;line-height:1.4;margin-top:6px;">{description_text}</div>'
        if description_text else ""
    )
    return (
        f'<div style="background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);'
        f'width:180px;overflow:hidden;display:inline-block;vertical-align:top;margin:0 8px 16px 0;">'
        f"{cover_html}"
        f'<div style="padding:8px 10px;">'
        f'<strong style="font-size:13px;line-height:1.3;display:block;">{title_escaped}</strong>'
        f'<span style="font-size:12px;color:#666;display:block;">{author_escaped}</span>'
        f"{description_html}"
        f"</div>"
        f"{link}"
        f"</div>"
    )


def render_email_html(sections: list[tuple[str, list[EBook]]], last_checked: str, library_name: str = "", library_base_url: str = "") -> str:
    """Render an email-safe HTML version with all styles inlined (no <style> block)."""
    groups = group_sections(sections)
    heading = page_heading(sections, last_checked, library_name)
    heading_escaped = _escape(heading)

    nav_html = ""
    if len(groups) >= 2:
        links = ['<a href="#top" style="color:#1a56c4;text-decoration:none;margin-right:16px;">Go to top</a>']
        for kind, _ in groups:
            meta = KIND_META[kind]
            links.append(
                f'<a href="#{meta["id"]}" style="color:#1a56c4;text-decoration:none;margin-right:16px;">'
                f'Go to {meta["nav"]}</a>'
            )
        nav_html = f'<div style="font-size:13px;margin-bottom:12px;">{"".join(links)}</div>'

    body_parts = []
    for kind, books in groups:
        meta = KIND_META[kind]
        section_heading = _escape(build_heading(len(books), "", "", noun=meta["noun"]))
        cards = "\n".join(_email_card_html(book, library_base_url) for book in books)
        body_parts.append(
            f'<h2 id="{meta["id"]}" style="font-size:17px;margin:20px 0 10px;color:#333;">{section_heading}</h2>\n'
            f"{cards}"
        )
    body_html = "\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{heading_escaped}</title>
</head>
<body id="top" style="font-family:system-ui,sans-serif;background:#f5f5f5;color:#222;padding:24px;margin:0;">
<h1 style="font-size:22px;margin:0 0 16px;color:#333;">{heading_escaped}</h1>
<div style="max-width:800px;">
{nav_html}
{body_html}
</div>
</body>
</html>"""


def write_and_open(html: str, output_path: Path, auto_open: bool = True) -> None:
    output_path.write_text(html, encoding="utf-8")
    if auto_open:
        webbrowser.open(output_path.as_uri())
