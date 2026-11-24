"""Ready-to-paste post drafts for each platform."""
from __future__ import annotations

PLATFORMS = {
    "YouTube": "https://studio.youtube.com/",
    "TikTok": "https://www.tiktok.com/tiktokstudio/upload",
    "Instagram": "https://www.instagram.com/",
    "X": "https://x.com/compose/post",
}

# Added on top of the user's own hashtags for each platform.
EXTRA_TAGS = {
    "YouTube": ["#Shorts", "#Viral", "#Gaming"],
    "TikTok": ["#fyp", "#viral", "#foryou"],
    "Instagram": ["#reels", "#viral", "#explorepage"],
    "X": [],
}


def merge_tags(base: str, extra: list[str], limit: int | None = None) -> list[str]:
    seen, out = set(), []
    for t in base.split() + extra:
        t = t.strip()
        if not t:
            continue
        t = t if t.startswith("#") else "#" + t
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:limit] if limit else out


def build_draft(platform: str, caption: str, credit: str, tags: str) -> tuple[str, str]:
    """Return (title, body). `title` is empty for platforms that have no title field."""
    caption = caption.strip()
    credit_line = f"Credit: {credit.strip()}" if credit.strip() else ""
    t = merge_tags(tags, EXTRA_TAGS[platform])
    if platform == "YouTube":
        title = (caption or "New clip")[:100]
        parts = [caption, credit_line, "", " ".join(t), "", "Tags: " + ", ".join(x.lstrip("#") for x in t)]
        return title, "\n".join(parts).strip()
    if platform == "TikTok":
        return "", " ".join(x for x in [caption, " ".join(t)] if x)
    if platform == "Instagram":
        return "", "\n".join([caption, credit_line, "", " ".join(t)]).strip()
    short = merge_tags(tags, [], 3)
    body = f"{caption} {' '.join(short)}".strip()
    if credit_line:
        body += "\n" + credit_line
    return "", body[:280]
