"""AutoClipper engine: download (or open) a video, cut a clip, reformat it, add overlays.

Everything the app needs ships inside the app: ffmpeg comes from imageio-ffmpeg and
downloading is done with the yt-dlp Python API, so users install nothing else.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


ASSETS = Path(__file__).resolve().parent / "assets"
FALLBACK_FONTS = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
MAX_SECONDS = 180  # YouTube Shorts / Reels limit

Log = Callable[[str], None]


class EngineError(Exception):
    """A problem with a user-readable message."""


# ---------- small helpers ----------
def is_url(s: str) -> bool:
    return bool(re.match(r"https?://", s.strip()))


def slug(s: str, n: int = 60) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:n].strip("_") or "clip"


def parse_time(s: str) -> float:
    """'1:23:45' / '83:45' / '45' -> seconds."""
    try:
        out = 0.0
        for p in str(s).strip().split(":"):
            out = out * 60 + float(p)
        return out
    except ValueError:
        raise EngineError(f"'{s}' is not a time. Use a format like 0:53 or 1:02:10.")


def fmt_time(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        if found:
            return found
    raise EngineError("ffmpeg was not found. Reinstall the app.")


def _run_ffmpeg(args: list[str]) -> None:
    r = subprocess.run([ffmpeg_exe(), "-y", "-v", "error", *args], capture_output=True,
                       text=True, errors="replace", creationflags=NO_WINDOW)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-4:])
        raise EngineError(f"Video processing failed:\n{tail}")


def probe(path: Path) -> tuple[Optional[int], Optional[int], Optional[float]]:
    """(width, height, duration seconds) read from `ffmpeg -i`; None where unknown."""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True,
                       text=True, errors="replace", creationflags=NO_WINDOW)
    txt = r.stderr
    w = h = dur = None
    m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", txt)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        rot = re.search(r"rotation of (-?\d+)", txt)
        if rot and abs(int(float(rot.group(1)))) in (90, 270):
            w, h = h, w
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if d:
        dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    return w, h, dur


def thumbnail(path: Path, height: int = 300) -> Optional[bytes]:
    """PNG bytes of a frame from the clip, for the preview."""
    for t in ("1", "0"):
        r = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", t, "-i", str(path), "-frames:v", "1",
                            "-vf", f"scale=-2:{height}", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, creationflags=NO_WINDOW)
        if r.stdout:
            return r.stdout
    return None


# ---------- finding the best moment ----------
def audio_levels(path: Path) -> list[float]:
    """Loudness (RMS) per second, lightly smoothed."""
    from array import array
    r = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", "8000", "-f", "s16le", "-"], capture_output=True,
                       creationflags=NO_WINDOW)
    x = array("h")
    x.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    n = len(x) // 8000
    if n == 0:
        return []
    rms = []
    for i in range(n):
        chunk = x[i * 8000:(i + 1) * 8000]
        rms.append(math.sqrt(sum(v * v for v in chunk) / 8000) / 32768.0)
    pad = [0.0] + rms + [0.0]
    return [(pad[i] + pad[i + 1] + pad[i + 2]) / 3 for i in range(n)]


def best_moment(levels: list[float], length: int) -> tuple[float, float]:
    """Start/end of a `length`-second window around the loudest second."""
    if len(levels) == 0 or max(levels) <= 0:
        return 0.0, float(length)
    peak = max(range(len(levels)), key=levels.__getitem__)
    pre = int(length * 0.55)
    start = max(0, min(peak - pre, max(0, len(levels) - length)))
    return float(start), float(start + length)


# ---------- downloading ----------
@dataclass
class Fetched:
    path: Path
    uploader: str = ""


class _YdlLogger:
    def __init__(self, log: Log):
        self.log = log

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.log(str(msg))


def _friendly_download_error(msg: str) -> str:
    low = msg.lower()
    if "no video could be found" in low or "sign in" in low or "log in" in low \
            or "login" in low or "age" in low and "restrict" in low or "nsfw" in low:
        return ("This post needs a signed-in account (adult-flagged or private). "
                "Open Settings and pick the browser you're signed in with, "
                "or download the video yourself and drop the file in.")
    if "unsupported url" in low:
        return "That link isn't supported. Paste a link to a post or video page."
    if "unavailable" in low or "removed" in low or "deleted" in low:
        return "That video is unavailable (it may have been deleted or made private)."
    return f"Download failed: {msg.strip().splitlines()[-1][:300]}"


def download(url: str, work: Path, name: str, log: Log, *, section: tuple[float, float] | None = None,
             audio_only: bool = False, cookies_browser: str = "", cookies_file: str = "") -> Fetched:
    import yt_dlp
    from yt_dlp.utils import DownloadError, download_range_func

    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob(f"{name}.*"):
        old.unlink()
    state = {"bucket": -1}

    def hook(d):
        tot = d.get("total_bytes") or d.get("total_bytes_estimate")
        if d.get("status") == "downloading" and tot:
            pct = int(100 * d.get("downloaded_bytes", 0) / tot)
            if pct // 25 != state["bucket"]:
                state["bucket"] = pct // 25
                log(f"Downloading... {pct}%")

    opts = {
        "format": "bestaudio/worst" if audio_only else "bv*[height<=1080]+ba/b[height<=1080]/b",
        "outtmpl": str(work / f"{name}.%(ext)s"),
        "noplaylist": True, "quiet": True, "no_warnings": True, "overwrites": True,
        "logger": _YdlLogger(log), "progress_hooks": [hook],
        "ffmpeg_location": ffmpeg_exe(),
    }
    if not audio_only:
        opts["merge_output_format"] = "mp4"
    if section:
        opts["download_ranges"] = download_range_func(None, [section])
        opts["force_keyframes_at_cuts"] = True
    if cookies_file and Path(cookies_file).is_file():
        opts["cookiefile"] = cookies_file
    elif cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser.lower(),)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
    except DownloadError as ex:
        raise EngineError(_friendly_download_error(str(ex)))
    except Exception as ex:
        raise EngineError(_friendly_download_error(str(ex)))
    files = sorted(work.glob(f"{name}.*"))
    if not files:
        raise EngineError("The download finished but no file was saved.")
    up = info.get("uploader") or info.get("channel") or ""
    return Fetched(files[0], "" if up == "NA" else up)


# ---------- overlays ----------
FONTS = {  # key -> (label shown in the app, bundled file)
    "clean": ("Clean", "Poppins-Bold.ttf"),
    "bold": ("Bold", "Anton-Regular.ttf"),
    "gaming": ("Gaming", "Bangers-Regular.ttf"),
    "script": ("Script", "Pacifico-Regular.ttf"),
}


def _font(size: int, kind: str = "clean"):
    from PIL import ImageFont
    kind = "bold" if kind == "display" else kind
    name = FONTS.get(kind, FONTS["clean"])[1]
    for f in [str(ASSETS / "fonts" / name), *FALLBACK_FONTS]:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_png(text: str, path: Path, size: int = 44, font_key: str = "clean") -> Path:
    from PIL import Image, ImageDraw
    font = _font(size, font_key)
    l, t, r, b = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
    img = Image.new("RGBA", (r - l + 28, b - t + 28), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((16 - l, 16 - t), text, font=font, fill=(0, 0, 0, 160))
    d.text((14 - l, 14 - t), text, font=font, fill=(255, 255, 255, 235))
    img.save(path)
    return path


def watermark_png(text: str, logo: str, path: Path, font_key: str = "clean") -> Path:
    """Build the watermark image from text, a logo file, or both (logo and text on one line)."""
    from PIL import Image
    text, logo = (text or "").strip(), (logo or "").strip()
    mark = None
    if logo:
        if not Path(logo).is_file():
            raise EngineError("The watermark logo file was not found.")
        try:
            im = Image.open(logo).convert("RGBA")
        except Exception:
            raise EngineError("The watermark logo could not be opened. Use a PNG or JPG image.")
        h = 54 if text else 80   # logo height in pixels
        mark = im.resize((max(1, int(h * im.width / im.height)), h), Image.LANCZOS)
        if mark.width > 220:
            mark = mark.resize((220, max(1, int(220 * im.height / im.width))), Image.LANCZOS)
    words = None
    if text:
        words = Image.open(text_png(text, path, 34 if mark else 52, font_key)).convert("RGBA")
        words = words.crop(words.getbbox() or (0, 0, words.width, words.height))
    if mark is None and words is None:
        raise EngineError("No watermark text or logo was given.")
    parts = [x for x in (mark, words) if x is not None]
    gap = 12 if len(parts) == 2 else 0
    out = Image.new("RGBA", (sum(p.width for p in parts) + gap, max(p.height for p in parts)), (0, 0, 0, 0))
    x = 0
    for part in parts:   # same vertical centre, side by side
        out.paste(part, (x, (out.height - part.height) // 2), part)
        x += part.width + gap
    out.save(path)
    return path


def hook_png(text: str, path: Path, size: int = 66, width: int = 1000) -> Path:
    from PIL import Image, ImageDraw
    font = _font(size, "display")
    lines = textwrap.wrap(text.upper(), 28) or [text.upper()]
    probe_d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lh = probe_d.textbbox((0, 0), "Ag", font=font)[3] + 14
    img = Image.new("RGBA", (width, lh * len(lines) + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        w = probe_d.textbbox((0, 0), ln, font=font)[2]
        d.text(((width - w) / 2, 8 + i * lh), ln, font=font, fill="white",
               stroke_width=5, stroke_fill="black")
    img.save(path)
    return path


# ---------- encoding ----------
def encode_short(src: Path, dst: Path, style: str, dur: float, ss: float | None,
                 credit_png: Path | None, wm: Path | None, hook: Path | None, enhance: bool) -> None:
    inputs: list[str] = []
    if ss is not None:
        inputs += ["-ss", str(ss)]
    inputs += ["-i", str(src)]
    w, h, _ = probe(src)
    if w and h and w / h < 0.75:  # already vertical: just fill the frame
        style = "fill"
    grade = ",eq=contrast=1.06:saturation=1.15,unsharp=5:5:0.6" if enhance else ""
    if style == "fill":
        graph = [f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920{grade}[v0]"]
    elif style == "crop":
        graph = [f"[0:v]scale=-2:1920,crop=1080:1920:(iw-1080)*0.5:0{grade}[v0]"]
    elif style == "frame":
        graph = ["[0:v]split[a][b]",
                 "[a]scale=1080:1920:force_original_aspect_ratio=increase,"
                 "crop=1080:1920,boxblur=25:5,eq=brightness=-0.08[bg]",
                 f"[b]crop=ih*0.8:ih:(iw-ih*0.8)*0.5:0,scale=1080:1350{grade}[fg]",
                 "[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]"]
    else:  # blur
        graph = ["[0:v]split[a][b]",
                 "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg]",
                 f"[b]scale=1080:-2{grade}[fg]",
                 "[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]"]
    cur, n = "v0", 1
    for png, pos in ((credit_png, "30:150"), (wm, "W-w-30:H-h-60"), (hook, "(W-w)/2:310")):
        if png:
            inputs += ["-i", str(png)]
            graph.append(f"[{cur}][{n}:v]overlay={pos}[v{n}]")
            cur, n = f"v{n}", n + 1
    _run_ffmpeg([*inputs, "-filter_complex", ";".join(graph), "-map", f"[{cur}]", "-map", "0:a?",
                 "-t", str(dur), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "160k",
                 "-movflags", "+faststart", str(dst)])


def encode_wide(src: Path, dst: Path, dur: float, ss: float | None,
                credit_png: Path | None, wm: Path | None, enhance: bool) -> None:
    inputs: list[str] = []
    if ss is not None:
        inputs += ["-ss", str(ss)]
    inputs += ["-i", str(src)]
    grade = ",eq=contrast=1.06:saturation=1.15,unsharp=5:5:0.6" if enhance else ""
    graph = ["[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
             f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2{grade}[v0]"]
    cur, n = "v0", 1
    if credit_png:
        inputs += ["-i", str(credit_png)]
        graph.append(f"[{cur}][{n}:v]overlay=40:40[v{n}]")
        cur, n = f"v{n}", n + 1
    if wm:
        inputs += ["-i", str(wm)]
        graph.append(f"[{n}:v]scale=-1:90[wm{n}]")
        graph.append(f"[{cur}][wm{n}]overlay=W-w-30:H-h-30[v{n}]")
        cur, n = f"v{n}", n + 1
    _run_ffmpeg([*inputs, "-filter_complex", ";".join(graph), "-map", f"[{cur}]", "-map", "0:a?",
                 "-t", str(dur), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", str(dst)])


# ---------- the job ----------
@dataclass
class Job:
    source: str
    out_dir: Path
    mode: str = "whole"          # whole | trim | auto
    seconds: int = 59            # length for whole / auto, and the cap for trim
    start: str = ""
    end: str = ""
    aspect: str = "9:16"         # 9:16 | 16:9
    style: str = "frame"         # frame | blur | crop (9:16 only)
    enhance: bool = True
    watermark_text: str = ""
    watermark_logo: str = ""     # path to a logo image
    watermark_font: str = "clean"
    caption: str = ""
    show_caption: bool = True
    credit: str = ""             # "" none | "auto" | custom text
    cookies_browser: str = ""
    cookies_file: str = ""


@dataclass
class Result:
    path: Path
    credit_name: str = ""


def _unique(out_dir: Path, name: str) -> Path:
    p, i = out_dir / f"{name}.mp4", 2
    while p.exists():
        p = out_dir / f"{name}_{i}.mp4"
        i += 1
    return p


def make_clip(job: Job, log: Log = print) -> Result:
    src_text = job.source.strip().strip('"')
    if not src_text:
        raise EngineError("Paste a link or choose a video file first.")
    seconds = max(3, min(int(job.seconds), MAX_SECONDS))
    job.out_dir.mkdir(parents=True, exist_ok=True)
    work = job.out_dir / "_sources"
    tmp = Path(tempfile.mkdtemp(prefix="autoclipper_"))
    name_base = slug(job.caption) if job.caption.strip() else None
    try:
        fetched: Optional[Fetched] = None
        ck = dict(cookies_browser=job.cookies_browser, cookies_file=job.cookies_file)
        stem = name_base or (slug(src_text.rstrip("/").split("/")[-1].split("?")[0]) if is_url(src_text)
                             else slug(Path(src_text).stem))
        if job.mode == "trim":
            s = parse_time(job.start)
            e = parse_time(job.end) if job.end.strip() else s + seconds
            if e <= s:
                raise EngineError("The end time must be after the start time.")
            dur = min(e - s, MAX_SECONDS)
        elif job.mode == "auto":
            dur, s = float(seconds), 0.0
        else:
            s, dur = 0.0, float(seconds)

        # 1. get the source video
        if is_url(src_text):
            log("Fetching the video...")
            if job.mode == "auto":
                log("Finding the loudest moment...")
                audio = download(src_text, work, "_audio", log, audio_only=True, **ck)
                s, e = best_moment(audio_levels(audio.path), seconds)
                log(f"Best moment starts at {fmt_time(s)}")
                fetched = download(src_text, work, stem, log, section=(s, e), **ck)
                src, ss = fetched.path, None
            elif job.mode == "trim":
                fetched = download(src_text, work, stem, log, section=(s, s + dur), **ck)
                src, ss = fetched.path, None
            else:
                fetched = download(src_text, work, stem, log, **ck)
                src, ss = fetched.path, None
        else:
            src = Path(src_text)
            if not src.is_file():
                raise EngineError(f"File not found: {src}")
            ss = s
            if job.mode == "auto":
                log("Finding the loudest moment...")
                s, e = best_moment(audio_levels(src), seconds)
                ss = s
                log(f"Best moment starts at {fmt_time(s)}")
        _, _, total = probe(src)
        if total and ss is None:
            dur = min(dur, total)
        elif total and ss is not None:
            dur = min(dur, max(1.0, total - ss))

        # 2. overlays
        credit_name = ""
        if job.credit.strip().lower() == "auto":
            credit_name = fetched.uploader if fetched else ""
        elif job.credit.strip():
            credit_name = job.credit.strip()
        credit_png = text_png(f"Source: {credit_name}"[:34], tmp / "credit.png") if credit_name else None
        wm = (watermark_png(job.watermark_text, job.watermark_logo, tmp / "wm.png", job.watermark_font)
              if (job.watermark_text.strip() or job.watermark_logo.strip()) else None)
        hook = None
        if job.caption.strip() and job.show_caption and job.aspect == "9:16":
            hook = hook_png(job.caption.strip(), tmp / "hook.png")

        # 3. encode
        wide = job.aspect == "16:9"
        dst = _unique(job.out_dir, stem + ("_16x9" if wide else ""))
        log("Editing the clip...")
        if wide:
            encode_wide(src, dst, dur, ss, credit_png, wm, job.enhance)
        else:
            encode_short(src, dst, job.style, dur, ss, credit_png, wm, hook, job.enhance)
        log(f"Done: {dst.name}")
        return Result(dst, credit_name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
