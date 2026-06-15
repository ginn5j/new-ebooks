import json

from new_ebooks.config import Config, LibraryConfig, load_config, save_config


def test_language_defaults_to_none():
    lib = LibraryConfig(name="L", library_base_url="https://spl.overdrive.com")
    assert lib.language is None


def test_language_round_trips(tmp_path):
    path = tmp_path / "config.json"
    config = Config(libraries=[
        LibraryConfig(name="O", library_base_url="https://spl.overdrive.com", language="english"),
        LibraryConfig(name="C", library_base_url="https://ebook.yourcloudlibrary.com/library/scpl",
                      provider="cloudlibrary", language="all"),
    ])
    save_config(config, path)

    loaded = load_config(path)
    assert loaded.libraries[0].language == "english"
    assert loaded.libraries[1].language == "all"


def test_legacy_config_without_language_loads(tmp_path):
    """Configs written before the language field load with language=None."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"libraries": [
        {"name": "L", "library_base_url": "https://spl.overdrive.com", "provider": "overdrive"},
    ]}))

    loaded = load_config(path)
    assert loaded.libraries[0].language is None


def test_formats_round_trip(tmp_path):
    path = tmp_path / "config.json"
    config = Config(libraries=[
        LibraryConfig(name="O", library_base_url="https://spl.overdrive.com",
                      formats=["ebook-kindle", "audiobook"]),
    ])
    save_config(config, path)

    loaded = load_config(path)
    assert loaded.libraries[0].formats == ["ebook-kindle", "audiobook"]


def test_default_formats():
    lib = LibraryConfig(name="L", library_base_url="https://spl.overdrive.com")
    assert lib.formats == ["ebook-kindle"]


def test_legacy_single_format_migrates_to_formats(tmp_path):
    """Configs written with the old single 'format' key become a one-element list."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"libraries": [
        {"name": "L", "library_base_url": "https://spl.overdrive.com",
         "format": "ebook-kindle", "provider": "overdrive"},
    ]}))

    loaded = load_config(path)
    assert loaded.libraries[0].formats == ["ebook-kindle"]


def test_save_config_omits_legacy_format_key(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(libraries=[
        LibraryConfig(name="L", library_base_url="https://x.com", formats=["digital"]),
    ]), path)
    data = json.loads(path.read_text())
    assert "format" not in data["libraries"][0]
    assert data["libraries"][0]["formats"] == ["digital"]
