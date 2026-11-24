"""User settings, saved as JSON in the user's profile."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "AutoClipper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_out_dir() -> Path:
    for sub in ("Videos", "Documents"):
        p = Path.home() / sub
        if p.is_dir():
            return p / "AutoClipper"
    return Path.home() / "AutoClipper"


@dataclass
class Settings:
    out_dir: str = ""
    watermark_mode: str = "off"    # off, text, logo, both
    watermark_text: str = ""
    watermark_logo: str = ""
    watermark_font: str = "clean"
    hashtags: str = "#gaming"
    cookies_browser: str = ""      # firefox, edge, chrome, brave...
    cookies_file: str = ""

    @property
    def output_path(self) -> Path:
        return Path(self.out_dir) if self.out_dir else default_out_dir()


def load() -> Settings:
    try:
        data = json.loads((config_dir() / "settings.json").read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in Settings.__dataclass_fields__}
        return Settings(**known)
    except Exception:
        return Settings()


def save(s: Settings) -> None:
    (config_dir() / "settings.json").write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
