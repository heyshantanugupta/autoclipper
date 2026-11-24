import subprocess

import pytest

from autoclipper import engine
from autoclipper.engine import EngineError, Job, make_clip, parse_time, probe


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    p = tmp_path_factory.mktemp("src") / "sample.mp4"
    subprocess.run([engine.ffmpeg_exe(), "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=12",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)], check=True)
    return p


def job(src, out, **kw):
    return Job(source=str(src), out_dir=out, **kw)


def test_parse_time():
    assert parse_time("1:02:03") == 3723
    assert parse_time("0:53") == 53
    with pytest.raises(EngineError):
        parse_time("abc")


def test_short_9x16(sample, tmp_path):
    res = make_clip(job(sample, tmp_path, seconds=6, caption="Hello world", credit="@me",
                        watermark_text="@brand", watermark_font="gaming"))
    w, h, dur = probe(res.path)
    assert (w, h) == (1080, 1920)
    assert 5 < dur < 7
    assert res.path.name == "Hello_world.mp4"


def test_wide_16x9(sample, tmp_path):
    res = make_clip(job(sample, tmp_path, aspect="16:9", seconds=5, caption="Wide"))
    w, h, _ = probe(res.path)
    assert (w, h) == (1920, 1080)
    assert res.path.name.endswith("_16x9.mp4")


def test_trim_section(sample, tmp_path):
    res = make_clip(job(sample, tmp_path, mode="trim", start="0:02", end="0:07", style="blur"))
    _, _, dur = probe(res.path)
    assert 4 < dur < 6


def test_auto_mode(sample, tmp_path):
    res = make_clip(job(sample, tmp_path, mode="auto", seconds=5, style="crop"))
    _, _, dur = probe(res.path)
    assert 4 < dur < 6


def test_longer_than_59_is_allowed(sample, tmp_path):
    res = make_clip(job(sample, tmp_path, seconds=10))
    assert probe(res.path)[2] > 9


def test_unique_names(sample, tmp_path):
    a = make_clip(job(sample, tmp_path, seconds=3, caption="Same"))
    b = make_clip(job(sample, tmp_path, seconds=3, caption="Same"))
    assert a.path != b.path


def test_bad_inputs(tmp_path):
    with pytest.raises(EngineError):
        make_clip(job("", tmp_path))
    with pytest.raises(EngineError):
        make_clip(job(tmp_path / "missing.mp4", tmp_path))
    with pytest.raises(EngineError):
        make_clip(job("x.mp4", tmp_path, mode="trim", start="0:10", end="0:05"))


def test_thumbnail(sample, tmp_path):
    res = make_clip(job(sample, tmp_path, seconds=3))
    png = engine.thumbnail(res.path)
    assert png and png.startswith(b"\x89PNG")


def test_watermark_variants(sample, tmp_path):
    from PIL import Image
    from autoclipper.engine import FONTS, watermark_png
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (300, 100), (255, 0, 0, 255)).save(logo)
    for key in FONTS:
        assert watermark_png("@brand", "", tmp_path / f"t_{key}.png", key).exists()
    both = Image.open(watermark_png("@brand", str(logo), tmp_path / "both.png", "script"))
    only = Image.open(watermark_png("", str(logo), tmp_path / "only.png"))
    assert both.height > only.height
    with pytest.raises(EngineError):
        watermark_png("", "", tmp_path / "x.png")
    with pytest.raises(EngineError):
        watermark_png("", str(tmp_path / "missing.png"), tmp_path / "y.png")
    res = make_clip(job(sample, tmp_path, seconds=4, caption="Logo", watermark_logo=str(logo), watermark_text="hi"))
    assert probe(res.path)[:2] == (1080, 1920)
