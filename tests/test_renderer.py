from new_ebooks.renderer import render_html, render_email_html
from new_ebooks.scraper import EBook


def make_book(id_: str, title: str, author: str, cover: str = "", is_available: bool = False) -> EBook:
    return EBook(overdrive_id=id_, reserve_id=f"r{id_}", title=title, first_creator_name=author, cover_url=cover, is_available=is_available)


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
    assert "2026-03-01" in html


def test_render_html_no_books():
    html = render_html([], "2026-03-01", "Empty Library")
    assert "No new eBooks" in html


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
    assert "2026-03-01" in html


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
