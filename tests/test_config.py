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


def test_max_result_files_defaults_to_ten():
    assert Config().max_result_files == 10


def test_max_result_files_round_trips(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(max_result_files=3), path)
    assert load_config(path).max_result_files == 3


def test_legacy_config_without_max_result_files_loads(tmp_path):
    """Configs written before max_result_files default to 10 on load."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"libraries": []}))
    assert load_config(path).max_result_files == 10


def test_unknown_library_keys_are_ignored(tmp_path):
    """A config with a field a newer version added still loads (no TypeError)."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"libraries": [
        {"name": "L", "library_base_url": "https://spl.overdrive.com",
         "provider": "overdrive", "future_setting": "value"},
    ]}))
    loaded = load_config(path)
    assert loaded.libraries[0].name == "L"
    assert not hasattr(loaded.libraries[0], "future_setting")


def test_unknown_email_keys_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "libraries": [],
        "email": {"smtp_host": "smtp.example.com", "smtp_to": "a@b.c", "future": 1},
    }))
    loaded = load_config(path)
    assert loaded.email.smtp_host == "smtp.example.com"


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
        LibraryConfig(name="L", library_base_url="https://x.com", formats=["ebook-kindle"]),
    ]), path)
    data = json.loads(path.read_text())
    assert "format" not in data["libraries"][0]
    assert data["libraries"][0]["formats"] == ["ebook-kindle"]


def test_cloudlibrary_legacy_format_values_migrate(tmp_path):
    """CloudLibrary 'digital'/'audio' format values migrate to 'ebook'/'audiobook'."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"libraries": [
        {"name": "C", "library_base_url": "https://ebook.yourcloudlibrary.com/library/scpl",
         "provider": "cloudlibrary", "formats": ["digital", "audio"]},
    ]}))

    loaded = load_config(path)
    assert loaded.libraries[0].formats == ["ebook", "audiobook"]


def test_cloudlibrary_legacy_single_format_migrates(tmp_path):
    """A legacy single 'format' value on a CloudLibrary entry is also migrated."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"libraries": [
        {"name": "C", "library_base_url": "https://ebook.yourcloudlibrary.com/library/scpl",
         "provider": "cloudlibrary", "format": "digital"},
    ]}))

    loaded = load_config(path)
    assert loaded.libraries[0].formats == ["ebook"]


def test_overdrive_format_values_not_migrated(tmp_path):
    """Overdrive entries are untouched by the CloudLibrary format migration."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"libraries": [
        {"name": "O", "library_base_url": "https://spl.overdrive.com",
         "provider": "overdrive", "formats": ["ebook-kindle", "audiobook"]},
    ]}))

    loaded = load_config(path)
    assert loaded.libraries[0].formats == ["ebook-kindle", "audiobook"]
