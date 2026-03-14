from pathlib import Path
from new_ebooks.scraper import build_search_url, extract_media_items, extract_title_collection, parse_page

FIXTURE = Path(__file__).parent / "fixtures" / "sample_page.html"


def test_build_search_url():
    url = build_search_url("https://spl.overdrive.com", "ebook-kindle", 1)
    assert url == "https://spl.overdrive.com/search/title?format=ebook-kindle&sortBy=newlyadded&page=1"


def test_build_search_url_page3():
    url = build_search_url("https://spl.overdrive.com/", "ebook-epub", 3)
    assert url == "https://spl.overdrive.com/search/title?format=ebook-epub&sortBy=newlyadded&page=3"


def test_extract_media_items():
    script = 'window.OverDrive.mediaItems = {"111": {"id": "111", "title": "Test"}};'
    items = extract_media_items(script)
    assert "111" in items
    assert items["111"]["title"] == "Test"


def test_extract_media_items_no_match():
    assert extract_media_items("no match here") == {}


def test_extract_title_collection():
    script = '''window.OverDrive.titleCollection = [
      {"id": "1", "reserveId": "uuid-1", "title": "First", "firstCreatorName": "A", "covers": {}},
      {"id": "2", "reserveId": "uuid-2", "title": "Second", "firstCreatorName": "B", "covers": {}}
    ];'''
    items = extract_title_collection(script)
    assert len(items) == 2
    assert items[0]["id"] == "1"
    assert items[1]["reserveId"] == "uuid-2"


def test_extract_title_collection_no_match():
    assert extract_title_collection("no match here") == []


def test_parse_page_fixture_uses_title_collection_order():
    """titleCollection order (87654321, 11111111, 12345678) should be used."""
    html = FIXTURE.read_text()
    books = parse_page(html)
    assert len(books) == 3
    assert books[0].overdrive_id == "87654321"
    assert books[0].title == "Recursive Dreams"
    assert books[0].first_creator_name == "Brian Stack"
    assert books[0].cover_url == "https://img1.od-cdn.com/ImageType-100/1191-1/RecDreams.jpg"
    assert "A recursive tale of wonder." in books[0].description
    assert books[1].overdrive_id == "11111111"
    assert books[1].cover_url == ""  # no covers
    assert books[2].overdrive_id == "12345678"
    assert books[2].first_creator_name == "Ada Coder"


def test_parse_page_fallback_to_media_items():
    """When titleCollection is absent, fall back to mediaItems insertion order."""
    html = """<html><body><script>
window.OverDrive = window.OverDrive || {};
window.OverDrive.mediaItems = {
  "aaa": {"id": "aaa", "reserveId": "r1", "title": "First", "creators": [{"name": "A"}], "covers": {}},
  "bbb": {"id": "bbb", "reserveId": "r2", "title": "Second", "creators": [{"name": "B"}], "covers": {}}
};
</script></body></html>"""
    books = parse_page(html)
    assert len(books) == 2
    assert books[0].overdrive_id == "aaa"
    assert books[1].overdrive_id == "bbb"


def test_parse_page_empty():
    assert parse_page("<html></html>") == []
