from autoclipper.drafts import build_draft, merge_tags


def test_merge_tags_dedupes_and_prefixes():
    assert merge_tags("#GTAVI gta6 #gtavi", ["#Viral"]) == ["#GTAVI", "#gta6", "#Viral"]


def test_youtube_has_title_and_tags():
    title, body = build_draft("YouTube", "Mandy is crazy", "", "#GTAVI")
    assert title == "Mandy is crazy"
    assert "#Shorts" in body and "Tags:" in body and "Credit" not in body


def test_credit_included_when_given():
    _, body = build_draft("Instagram", "Hi", "@someone", "#a")
    assert "Credit: @someone" in body


def test_x_fits_280():
    _, body = build_draft("X", "word " * 100, "@x", "#a #b #c #d #e")
    assert len(body) <= 280


def test_tiktok_no_title():
    title, body = build_draft("TikTok", "Hi", "", "#a")
    assert title == "" and "#fyp" in body
