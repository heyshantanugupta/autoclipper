"""Build a single-file desktop app with PyInstaller.

    python build.py

On Windows this produces dist/AutoClipper.exe (ffmpeg and yt-dlp are bundled).
"""
import os
import subprocess
import sys

sep = os.pathsep
cmd = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "AutoClipper",
    "--collect-all", "tkinterdnd2",
    "--collect-all", "imageio_ffmpeg",
    "--collect-all", "yt_dlp",
    "--add-data", f"autoclipper/assets{sep}autoclipper/assets",
    "run.py",
]
sys.exit(subprocess.call(cmd))
