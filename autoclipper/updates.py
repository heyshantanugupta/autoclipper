"""Check GitHub for a newer release."""
from __future__ import annotations

import json
import re
import urllib.request

API = "https://api.github.com/repos/heyshantanugupta/autoclipper/releases/latest"
PAGE = "https://github.com/heyshantanugupta/autoclipper/releases/latest"


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def is_newer(latest: str, current: str) -> bool:
    try:
        return _ver(latest) > _ver(current)
    except Exception:
        return False


def latest_version(timeout: float = 6.0) -> str:
    """Return the newest release tag such as '0.1.2', or '' if it can't be fetched."""
    try:
        req = urllib.request.Request(API, headers={"User-Agent": "AutoClipper"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return str(json.load(r).get("tag_name", "")).lstrip("vV")
    except Exception:
        return ""
