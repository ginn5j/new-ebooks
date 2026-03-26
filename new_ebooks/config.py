from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "new_ebooks"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"


@dataclass
class LibraryConfig:
    name: str
    library_base_url: str
    format: str = "ebook-kindle"
    request_delay_seconds: float = 1.0
    member_library: Optional[str] = None


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
    email: Optional[EmailConfig] = None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    data = json.loads(path.read_text())
    libraries = [LibraryConfig(**lib) for lib in data.get("libraries", [])]
    email = None
    if "email" in data and data["email"]:
        email = EmailConfig(**data["email"])
    return Config(
        libraries=libraries,
        max_state_backups=data.get("max_state_backups", 10),
        email=email,
    )


def save_config(config: Config, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "libraries": [asdict(lib) for lib in config.libraries],
        "max_state_backups": config.max_state_backups,
    }
    if config.email is not None:
        data["email"] = asdict(config.email)
    path.write_text(json.dumps(data, indent=2))
