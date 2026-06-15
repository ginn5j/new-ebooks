from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Optional


def _known_fields(cls, data: dict) -> dict:
    """Keep only keys matching ``cls``'s dataclass fields.

    Lets a config written by a newer version (with extra keys) load on an
    older one instead of raising TypeError from an unexpected argument.
    """
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in valid}

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "new_ebooks"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"


@dataclass
class LibraryConfig:
    name: str
    library_base_url: str
    # One or more media formats to track for this library (e.g. an eBook
    # format plus "audiobook"). Each format is searched separately and keeps
    # its own anchor. The first format is the "primary" one — see load_state
    # for how a legacy single-format anchor is migrated.
    formats: list[str] = field(default_factory=lambda: ["ebook-kindle"])
    request_delay_seconds: float = 1.0
    member_library: Optional[str] = None
    provider: str = "overdrive"
    # Language filter: "all", "english", or None (unset → preserve the
    # provider's default behavior). See each provider's build_search_url.
    language: Optional[str] = None


@dataclass
class EmailConfig:
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    use_tls: bool = True


@dataclass
class Config:
    libraries: list[LibraryConfig] = field(default_factory=list)
    max_state_backups: int = 10
    # How many rendered result HTML files to keep on disk, newest first, so a
    # user can review recent runs if they suspect a problem. 0 (or less)
    # disables pruning and keeps every run.
    max_result_files: int = 10
    email: Optional[EmailConfig] = None


# CloudLibrary format config values were once the raw query values
# ("digital"/"audio"). They now use the friendly tokens shared with Overdrive
# and the renderer ("ebook"/"audiobook"), mapped to query values in
# cloudlibrary.build_search_url. Silently migrate old config entries on load.
_CLOUDLIBRARY_FORMAT_MIGRATION = {"digital": "ebook", "audio": "audiobook"}


def _library_from_dict(lib: dict) -> LibraryConfig:
    """Build a LibraryConfig, migrating legacy format values.

    Older config files stored one ``format`` string per library; new ones
    store a ``formats`` list. A legacy entry becomes a single-element list.
    For CloudLibrary libraries, legacy ``digital``/``audio`` format values are
    migrated to the standardized ``ebook``/``audiobook`` tokens.
    """
    lib = dict(lib)
    legacy_format = lib.pop("format", None)
    if "formats" not in lib and legacy_format is not None:
        lib["formats"] = [legacy_format]
    if lib.get("provider") == "cloudlibrary" and "formats" in lib:
        lib["formats"] = [
            _CLOUDLIBRARY_FORMAT_MIGRATION.get(fmt, fmt) for fmt in lib["formats"]
        ]
    return LibraryConfig(**_known_fields(LibraryConfig, lib))


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    data = json.loads(path.read_text())
    libraries = [_library_from_dict(lib) for lib in data.get("libraries", [])]
    email = None
    if "email" in data and data["email"]:
        email = EmailConfig(**_known_fields(EmailConfig, data["email"]))
    return Config(
        libraries=libraries,
        max_state_backups=data.get("max_state_backups", 10),
        max_result_files=data.get("max_result_files", 10),
        email=email,
    )


def save_config(config: Config, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "libraries": [asdict(lib) for lib in config.libraries],
        "max_state_backups": config.max_state_backups,
        "max_result_files": config.max_result_files,
    }
    if config.email is not None:
        data["email"] = asdict(config.email)
    path.write_text(json.dumps(data, indent=2))
