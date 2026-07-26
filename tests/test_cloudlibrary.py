import json

from new_ebooks.cloudlibrary import build_search_url, is_authenticated, parse_page

# --- build_search_url ---

def test_build_search_url_basic():
    url = build_search_url("https://ebook.yourcloudlibrary.com/library/scpl", "ebook", 1)
    assert "_data=routes%2Flibrary.%24name.search" in url
    assert "sort=-dateadded" in url
    assert "format=digital" in url  # "ebook" config token maps to "digital"
    assert "language=eng" in url
    assert "segment=1" in url


def test_build_search_url_audiobook_format_value():
    """The "audiobook" config token maps to CloudLibrary's "audio" query value."""
    url = build_search_url("https://ebook.yourcloudlibrary.com/library/scpl/", "audiobook", 3)
    assert "segment=3" in url
    assert "format=audio" in url
    assert not url.endswith("/search")  # trailing slash stripped from base


def test_build_search_url_unknown_format_passes_through():
    """A value not in the map is used verbatim as the query value."""
    url = build_search_url("https://ebook.yourcloudlibrary.com/library/scpl", "digital", 1)
    assert "format=digital" in url


def test_build_search_url_no_trailing_slash():
    url1 = build_search_url("https://ebook.yourcloudlibrary.com/library/scpl", "ebook", 1)
    url2 = build_search_url("https://ebook.yourcloudlibrary.com/library/scpl/", "ebook", 1)
    assert url1 == url2


def test_build_search_url_language_default_is_english():
    """Default (no language arg) preserves the original English-only behavior."""
    url = build_search_url("https://ebook.yourcloudlibrary.com/library/scpl", "ebook", 1)
    assert "language=eng" in url


def test_build_search_url_language_english():
    url = build_search_url(
        "https://ebook.yourcloudlibrary.com/library/scpl", "ebook", 1, language="english"
    )
    assert "language=eng" in url


def test_build_search_url_language_all_no_filter():
    url = build_search_url(
        "https://ebook.yourcloudlibrary.com/library/scpl", "ebook", 1, language="all"
    )
    assert "language=" not in url


# --- parse_page ---

SAMPLE_JSON = json.dumps({
    "results": {
        "search": {
            "totalItems": 2,
            "totalSegments": 1,
            "items": [
                {
                    "id": "abc123",
                    "title": "Test Book One",
                    "authors": ["Smith, John"],
                    "imageLinkThumbnail": "https://example.com/cover1.jpg",
                    "currentlyAvailable": 2,
                    "summary": "A great read.",
                },
                {
                    "id": "def456",
                    "title": "Test Book Two",
                    "authors": ["Jones, Mary", "Brown, Tom"],
                    "imageLinkThumbnail": "",
                    "currentlyAvailable": None,
                    "summary": "",
                },
            ],
        }
    },
    "segment": 1,
})


def test_parse_page_ids_and_titles():
    books = parse_page(SAMPLE_JSON)
    assert len(books) == 2
    assert books[0].overdrive_id == "abc123"
    assert books[0].title == "Test Book One"
    assert books[1].overdrive_id == "def456"
    assert books[1].title == "Test Book Two"


def test_parse_page_first_author():
    books = parse_page(SAMPLE_JSON)
    assert books[0].first_creator_name == "Smith, John"
    assert books[1].first_creator_name == "Jones, Mary"


def test_parse_page_cover_and_description():
    books = parse_page(SAMPLE_JSON)
    assert books[0].cover_url == "https://example.com/cover1.jpg"
    assert books[0].description == "A great read."
    assert books[1].cover_url == ""
    assert books[1].description == ""


def test_parse_page_availability():
    books = parse_page(SAMPLE_JSON)
    assert books[0].is_available is True   # currentlyAvailable=2
    assert books[1].is_available is False  # currentlyAvailable=null


def test_parse_page_detail_url():
    base = "https://ebook.yourcloudlibrary.com/library/scpl"
    books = parse_page(SAMPLE_JSON, library_base_url=base)
    assert books[0].detail_url == f"{base}/detail/abc123"
    assert books[1].detail_url == f"{base}/detail/def456"


def test_parse_page_detail_url_empty_without_base():
    books = parse_page(SAMPLE_JSON)
    assert books[0].detail_url == ""


def test_parse_page_no_authors():
    data = json.dumps({"results": {"search": {"items": [
        {"id": "x", "title": "No Author Book", "authors": [], "imageLinkThumbnail": "",
         "currentlyAvailable": None, "summary": ""}
    ]}}})
    books = parse_page(data)
    assert books[0].first_creator_name == ""


def test_parse_page_empty_items():
    data = json.dumps({"results": {"search": {"items": []}}})
    assert parse_page(data) == []


def test_parse_page_invalid_json():
    assert parse_page("not json at all") == []


def test_parse_page_missing_results_key():
    assert parse_page(json.dumps({"something": "else"})) == []


def test_parse_page_204_empty_string():
    assert parse_page("") == []


# --- is_authenticated ---

def test_is_authenticated_with_results_key():
    assert is_authenticated(json.dumps({"results": {}, "segment": 1})) is True


def test_is_authenticated_with_categories_key():
    assert is_authenticated(json.dumps({"categories": [], "results": {}})) is True


def test_is_authenticated_empty_string():
    assert is_authenticated("") is False


def test_is_authenticated_html():
    assert is_authenticated("<html><body>Sign in</body></html>") is False


def test_is_authenticated_json_without_results():
    assert is_authenticated(json.dumps({"error": "not found"})) is False
