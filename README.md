# AutoClipper

Turn a video link or file into a ready-to-post short, with a post draft for each platform.

1. Paste a link (YouTube, X, TikTok, Instagram, Twitch, Reddit and more) or drop a video file.
2. Pick the length: from the start, a section you choose, or the loudest moment.
3. Pick the format: Short (9:16) or Widescreen (16:9).
4. Add a caption, an optional credit and your hashtags, then click **Make clip**.
5. Click YouTube, TikTok, Instagram or X. The title, description and hashtags are copied for you to paste.

ffmpeg and yt-dlp are built in, so there is nothing else to install.

## Download

Get `AutoClipper.exe` from the latest release on the Releases page.

## Run from source

```
pip install -r requirements.txt
python run.py
```

Needs Python 3.10 or newer with tkinter (included in the Windows installer from python.org).

## Build the Windows app

```
build_windows.bat
```

Or push a tag such as `v0.1.0`. GitHub Actions builds `AutoClipper.exe` and attaches it to a release.

## Settings

Open **Settings** to set the save folder, a watermark (text or a logo image) and default hashtags.

Some posts only download when you are signed in (private or adult-flagged posts on X, for example).
In Settings, pick the browser you are signed in with, or point to a `cookies.txt` file.
Firefox is the most reliable. A cookies file is a login key to your account, so keep it private and never commit it.

## Tests

```
pip install pytest
python -m pytest
```

## Notes

- Clips are limited to 180 seconds, the Shorts limit.
- You are responsible for having the right to reuse any video you download. Credit creators when you can.
- Sites change often. If a link stops working, update yt-dlp (`pip install -U yt-dlp`) or build a fresh release.
