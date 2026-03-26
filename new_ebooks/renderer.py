from __future__ import annotations
import re
import webbrowser
from pathlib import Path

from new_ebooks.scraper import EBook

_ALL_TAGS_RE = re.compile(r'<[^>]+>')


def _sanitize_description(html: str) -> str:
    """Strip all HTML tags and return plain text, HTML-escaped for safe insertion."""
    text = _ALL_TAGS_RE.sub(" ", html)
    text = re.sub(r" {2,}", " ", text).strip()
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

PLACEHOLDER_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='150' height='200' "
    "viewBox='0 0 150 200'%3E%3Crect width='150' height='200' fill='%23ddd'/%3E"
    "%3Ctext x='75' y='110' font-size='14' text-anchor='middle' fill='%23999'%3ENo Cover%3C/text%3E%3C/svg%3E"
)

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #f5f5f5; color: #222; padding: 1.5rem; }
h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: #333; }
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


def render_html(books: list[EBook], last_checked: str, library_name: str = "", library_base_url: str = "") -> str:
    count = len(books)
    if count == 0:
        heading = "No new eBooks"
    elif count == 1:
        heading = "1 new eBook"
    else:
        heading = f"{count} new eBooks"

    if last_checked:
        heading += f" since {last_checked}"
    if library_name:
        heading += f" — {library_name}"

    cards = []
    for book in books:
        src = book.cover_url if book.cover_url else PLACEHOLDER_SVG
        title_escaped = book.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        author_escaped = book.first_creator_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if library_base_url:
            detail_url = f"{library_base_url.rstrip('/')}/media/{book.overdrive_id}"
            if book.is_available:
                link = f'<a class="book-link borrow" href="{detail_url}" target="_blank">Borrow</a>'
            else:
                link = f'<a class="book-link hold" href="{detail_url}" target="_blank">Place a Hold</a>'
        else:
            link = ""
        description = f'<div class="description">{_sanitize_description(book.description)}</div>' if book.description else ""
        card = (
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
        cards.append(card)

    cards_html = "\n".join(cards)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading}</title>
<style>{CSS}</style>
</head>
<body>
<h1>{heading}</h1>
<div class="grid">
{cards_html}
</div>
</body>
</html>"""


def render_email_html(books: list[EBook], last_checked: str, library_name: str = "", library_base_url: str = "") -> str:
    """Render an email-safe HTML version with all styles inlined (no <style> block)."""
    count = len(books)
    if count == 0:
        heading = "No new eBooks"
    elif count == 1:
        heading = "1 new eBook"
    else:
        heading = f"{count} new eBooks"

    if last_checked:
        heading += f" since {last_checked}"
    if library_name:
        heading += f" — {library_name}"

    cards = []
    for book in books:
        src = book.cover_url if book.cover_url else ""
        title_escaped = book.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        author_escaped = book.first_creator_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cover_html = (
            f'<img src="{src}" alt="Cover" width="150" height="200" '
            f'style="width:150px;height:200px;object-fit:contain;background:#eee;display:block;">'
            if src else
            '<div style="width:150px;height:200px;background:#ddd;display:flex;align-items:center;'
            'justify-content:center;color:#999;font-size:13px;">No Cover</div>'
        )
        if library_base_url:
            detail_url = f"{library_base_url.rstrip('/')}/media/{book.overdrive_id}"
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
        card = (
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
        cards.append(card)

    cards_html = "\n".join(cards)
    heading_escaped = heading.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{heading_escaped}</title>
</head>
<body style="font-family:system-ui,sans-serif;background:#f5f5f5;color:#222;padding:24px;margin:0;">
<h1 style="font-size:22px;margin:0 0 20px;color:#333;">{heading_escaped}</h1>
<div style="max-width:800px;">
{cards_html}
</div>
</body>
</html>"""


def write_and_open(html: str, output_path: Path, auto_open: bool = True) -> None:
    output_path.write_text(html, encoding="utf-8")
    if auto_open:
        webbrowser.open(output_path.as_uri())
