from new_ebooks.renderer import (
    build_heading,
    format_date,
    group_sections,
    media_kind,
    render_email_html,
    render_html,
)
from new_ebooks.scraper import EBook


def make_book(id_: str, title: str, author: str, cover: str = "", is_available: bool = False, detail_url: str = "") -> EBook:
    return EBook(overdrive_id=id_, reserve_id=f"r{id_}", title=title, first_creator_name=author, cover_url=cover, is_available=is_available, detail_url=detail_url)


def test_render_html_with_books():
    books = [
        make_book("1", "Python Mastery", "Guido V.", "https://example.com/cover.jpg"),
        make_book("2", "Async & Await", "Trio Author", ""),
    ]
    html = render_html(books, "2026-03-01", "Test Library")
    assert "2 new eBooks" in html
    assert "Python Mastery" in html
    assert "Guido V." in html
    assert "https://example.com/cover.jpg" in html
    assert "Async &amp; Await" in html  # & is escaped in HTML output
    assert "Trio Author" in html
    assert "Test Library" in html
    assert "Mar 1, 2026" in html


def test_render_html_no_books():
    html = render_html([], "2026-03-01", "Empty Library")
    assert "No new eBooks" in html


def test_render_html_warning_banner():
    books = [make_book("1", "One Book", "Solo Author")]
    warnings = ["The previously tracked ebook-kindle title was not found."]
    html = render_html(books, "2026-03-01", warnings=warnings)
    assert 'class="warning"' in html
    assert "was not found" in html
    # Banner appears before the book grid.
    assert html.index('class="warning"') < html.index('class="grid"')


def test_render_html_no_warning_banner_by_default():
    books = [make_book("1", "One Book", "Solo Author")]
    html = render_html(books, "2026-03-01")
    assert 'class="warning"' not in html


def test_render_html_warning_escaped():
    books = [make_book("1", "One Book", "Solo Author")]
    html = render_html(books, "2026-03-01", warnings=["<script>alert('x')</script>"])
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_render_email_warning_banner():
    books = [make_book("1", "One Book", "Solo Author")]
    html = render_email_html(books, "2026-03-01", warnings=["Anchor missing"])
    assert "Anchor missing" in html
    assert html.index("Anchor missing") < html.index("One Book")


def test_render_html_xss_prevention():
    books = [make_book("1", "<script>alert('xss')</script>", "Author & Co")]
    html = render_html(books, "2026-03-01")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_render_html_single_book():
    books = [make_book("1", "One Book", "Solo Author")]
    html = render_html(books, "2026-03-01")
    assert "1 new eBook" in html
    assert "1 new eBooks" not in html


def test_render_html_borrow_link():
    books = [make_book("99", "Available Book", "Author", is_available=True)]
    html = render_html(books, "2026-03-01", library_base_url="https://spl.overdrive.com")
    assert 'href="https://spl.overdrive.com/media/99"' in html
    assert "Borrow" in html
    assert "Place a Hold" not in html


def test_render_html_hold_link():
    books = [make_book("99", "Unavailable Book", "Author", is_available=False)]
    html = render_html(books, "2026-03-01", library_base_url="https://spl.overdrive.com")
    assert 'href="https://spl.overdrive.com/media/99"' in html
    assert "Place a Hold" in html
    assert ">Borrow<" not in html


def test_render_html_no_link_without_base_url():
    books = [make_book("99", "A Book", "Author")]
    html = render_html(books, "2026-03-01")
    assert "Borrow" not in html
    assert "Place a Hold" not in html


def test_render_html_description():
    books = [EBook(
        overdrive_id="1", reserve_id="r1", title="A Book", first_creator_name="Author",
        description="<strong>Bold intro.</strong><br />More text here."
    )]
    html = render_html(books, "2026-03-01")
    assert "Bold intro." in html
    assert "More text here." in html
    # Tags stripped from description — plain text only
    assert "<strong>Bold intro.</strong>" not in html


def test_render_html_description_decodes_html_entities():
    """HTML entities in descriptions are decoded to characters, not left literal."""
    books = [EBook(
        overdrive_id="1", reserve_id="r1", title="A Book", first_creator_name="Author",
        description="#1 NEW YORK TIMES BESTSELLER &bull; The best book &amp; more."
    )]
    for html in (render_html(books, "2026-03-01"), render_email_html(books, "2026-03-01")):
        assert "•" in html  # &bull; decoded to a real bullet
        assert "&bull;" not in html  # no literal entity left
        assert "&amp;bull;" not in html  # not double-escaped either
        assert "The best book &amp; more." in html  # bare & still safely escaped


def test_render_html_no_description_element_when_empty():
    books = [make_book("1", "A Book", "Author")]
    html = render_html(books, "2026-03-01")
    assert 'class="description"' not in html


def test_render_email_html_no_style_block():
    books = [make_book("1", "Python Mastery", "Guido V.", "https://example.com/cover.jpg")]
    html = render_email_html(books, "2026-03-01", "Test Library")
    assert "<style" not in html
    assert "style=" in html  # inline styles present
    assert "Python Mastery" in html
    assert "Guido V." in html
    assert "Test Library" in html
    assert "Mar 1, 2026" in html


def test_render_email_html_no_js():
    books = [make_book("1", "A Book", "Author")]
    html = render_email_html(books, "2026-03-01")
    assert "onerror" not in html
    assert "<script" not in html


def test_render_email_html_xss_prevention():
    books = [make_book("1", "<script>alert('xss')</script>", "Author & Co")]
    html = render_email_html(books, "2026-03-01")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_render_html_cloudlibrary_detail_url():
    """When detail_url is set on the book, it is used directly instead of /media/{id}."""
    detail = "https://ebook.yourcloudlibrary.com/library/scpl/detail/abc123"
    books = [make_book("abc123", "A Book", "Author", detail_url=detail)]
    html = render_html(books, "2026-03-01")
    assert f'href="{detail}"' in html
    assert "/media/abc123" not in html


def test_render_html_detail_url_overrides_base_url():
    """detail_url takes precedence over the /media/{id} fallback even when base_url is set."""
    detail = "https://ebook.yourcloudlibrary.com/library/scpl/detail/abc123"
    books = [make_book("abc123", "A Book", "Author", detail_url=detail)]
    html = render_html(books, "2026-03-01", library_base_url="https://spl.overdrive.com")
    assert f'href="{detail}"' in html
    assert "/media/abc123" not in html


def test_render_email_html_cloudlibrary_detail_url():
    detail = "https://ebook.yourcloudlibrary.com/library/scpl/detail/abc123"
    books = [make_book("abc123", "A Book", "Author", detail_url=detail)]
    html = render_email_html(books, "2026-03-01")
    assert f'href="{detail}"' in html
    assert "/media/abc123" not in html


def test_render_html_description_all_tags_stripped():
    """All HTML tags in descriptions must be stripped — display as plain text."""
    books = [
        EBook(overdrive_id="1", reserve_id="r1", title="Book One", first_creator_name="Author",
              description="<div><p>Intro.</p><p>More.</p></div>"),
        EBook(overdrive_id="2", reserve_id="r2", title="Book Two", first_creator_name="Author",
              description="<strong>Bold</strong> and <em>italic</em>."),
    ]
    html = render_html(books, "2026-03-01")
    # Text content preserved
    assert "Intro." in html
    assert "More." in html
    assert "Bold" in html
    assert "italic" in html
    # No raw tags from descriptions in output
    assert "<div>" not in html
    assert "<p>" not in html
    assert "<strong>Bold</strong>" not in html
    assert "<em>italic</em>" not in html
    # Both cards present as siblings (not nested)
    assert html.count('class="book-card"') == 2


def test_format_date():
    assert format_date("2026-03-01T09:30:00+00:00") == "Mar 1, 2026"
    assert format_date("2026-03-01") == "Mar 1, 2026"
    # Unparseable strings pass through unchanged
    assert format_date("the beginning") == "the beginning"
    assert format_date("") == ""


def test_build_heading():
    assert build_heading(0, "", "") == "No new eBooks"
    assert build_heading(1, "", "") == "1 new eBook"
    assert build_heading(5, "2026-03-01", "Test Library") == "5 new eBooks since Mar 1, 2026 — Test Library"


def test_render_html_url_attributes_escaped():
    """Quotes in scraped URLs must not break out of href/src attributes."""
    evil = 'https://example.com/x" onmouseover="alert(1)'
    books = [make_book("1", "A Book", "Author", cover=evil, detail_url=evil)]
    html = render_html(books, "2026-03-01")
    assert 'onmouseover="alert(1)' not in html
    assert "&quot;" in html


def test_render_email_html_url_attributes_escaped():
    evil = 'https://example.com/x" onmouseover="alert(1)'
    books = [make_book("1", "A Book", "Author", cover=evil, detail_url=evil)]
    html = render_email_html(books, "2026-03-01")
    assert 'onmouseover="alert(1)' not in html


def test_render_html_heading_escaped():
    html = render_html([], "2026-03-01", library_name="<b>Lib & Co</b>")
    assert "<b>Lib" not in html
    assert "&lt;b&gt;Lib &amp; Co&lt;/b&gt;" in html


# --- Grouping by media format ---


def test_media_kind():
    assert media_kind("audiobook") == "audiobook"
    assert media_kind("audio") == "audiobook"
    assert media_kind("ebook-kindle") == "ebook"
    assert media_kind("digital") == "ebook"


def test_group_sections_merges_ebook_formats_and_dedupes():
    sections = [
        ("ebook-kindle", [make_book("1", "A", "x"), make_book("2", "B", "x")]),
        ("ebook-epub-adobe", [make_book("2", "B", "x"), make_book("3", "C", "x")]),
        ("audiobook", [make_book("4", "D", "x")]),
    ]
    groups = group_sections(sections)
    assert [kind for kind, _ in groups] == ["ebook", "audiobook"]
    assert [b.overdrive_id for b in groups[0][1]] == ["1", "2", "3"]  # "2" de-duped
    assert [b.overdrive_id for b in groups[1][1]] == ["4"]


def test_group_sections_drops_empty():
    sections = [("ebook-kindle", [make_book("1", "A", "x")]), ("audiobook", [])]
    groups = group_sections(sections)
    assert [kind for kind, _ in groups] == ["ebook"]


def test_render_html_groups_with_nav():
    sections = [
        ("ebook-kindle", [make_book("e1", "E Book", "Auth")]),
        ("audiobook", [make_book("a1", "A Book", "Auth")]),
    ]
    html = render_html(sections, "2026-03-01", "Test Library")
    assert "2 new titles" in html
    assert 'id="ebooks"' in html
    assert 'id="audiobooks"' in html
    assert "1 new eBook" in html
    assert "1 new audiobook" in html
    # Top/bottom nav links by section, no "Go to top"
    assert "Go to top" not in html
    assert 'href="#top"' not in html
    assert '>eBooks</a>' in html
    assert '>Audiobooks</a>' in html
    # Repeated at the end via the static subnav, plus a back link in the
    # audiobook section.
    assert 'class="subnav"' in html
    assert 'href="#ebooks">Go to eBooks</a>' in html
    # Both top and bottom nav point at each section.
    assert html.count('href="#audiobooks"') >= 2


def test_render_html_single_section_no_nav():
    sections = [("ebook-kindle", [make_book("e1", "E", "A")])]
    html = render_html(sections, "2026-03-01")
    assert 'class="nav"' not in html
    assert "1 new eBook" in html


def test_render_html_audiobook_only_heading():
    sections = [("audiobook", [make_book("a1", "A", "Auth"), make_book("a2", "B", "Auth")])]
    html = render_html(sections, "2026-03-01", "Lib")
    assert "2 new audiobooks" in html


def test_render_email_html_groups_with_nav():
    sections = [
        ("digital", [make_book("e1", "E", "Auth")]),
        ("audio", [make_book("a1", "A", "Auth")]),
    ]
    html = render_email_html(sections, "2026-03-01", "Lib")
    assert 'href="#audiobooks"' in html
    assert 'href="#ebooks"' in html
    assert "1 new eBook" in html
    assert "1 new audiobook" in html


def test_build_heading_noun():
    assert build_heading(0, "", "", noun="audiobook") == "No new audiobooks"
    assert build_heading(1, "", "", noun="audiobook") == "1 new audiobook"
    assert build_heading(3, "", "", noun="audiobook") == "3 new audiobooks"
