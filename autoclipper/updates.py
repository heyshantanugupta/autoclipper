"""Check GitHub for a newer release and install it."""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

REPO = "heyshantanugupta/autoclipper"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"


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


# ---------- installing ----------
def is_installed() -> bool:
    """True when running from the Windows installer's folder (it leaves unins000.exe next to the app)."""
    return sys.platform == "win32" and (Path(sys.executable).parent / "unins000.exe").exists()


def asset_name(version: str, plat: str | None = None, machine: str | None = None,
               installed: bool | None = None) -> Optional[str]:
    plat = plat or sys.platform
    machine = (machine or platform.machine()).lower()
    if plat == "win32":
        if installed is None:
            installed = is_installed()
        kind = "Setup" if installed else "Portable"
        return f"AutoClipper-{kind}-{version}-windows-x64.exe"
    if plat == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        return f"AutoClipper-{version}-mac-{arch}.dmg"
    return None


def asset_url(version: str, name: str) -> str:
    return f"https://github.com/{REPO}/releases/download/v{version}/{name}"


def direct_url(version: str) -> str:
    """The file for this computer if we know it, otherwise the release page."""
    name = asset_name(version)
    return asset_url(version, name) if name else PAGE


def can_self_update() -> bool:
    """Only the packaged Windows app updates itself. On Mac the person drags the new app over the old one."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def download(url: str, dest: Path, progress: Callable[[float], None] = lambda f: None) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "AutoClipper"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                progress(done / total)
    if dest.stat().st_size < 1_000_000:
        raise RuntimeError("The downloaded update looks incomplete.")
    return dest


def windows_script(new_exe: Path, current_exe: Path) -> str:
    """Portable copy: wait for this app to exit, swap the file, start it again."""
    return (
        "@echo off\r\n"
        "set tries=0\r\n"
        ":retry\r\n"
        "ping 127.0.0.1 -n 2 >nul\r\n"
        f'move /y "{new_exe}" "{current_exe}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  set /a tries+=1\r\n"
        "  if %tries% lss 30 goto retry\r\n"
        "  goto done\r\n"
        ")\r\n"
        f'start "" "{current_exe}"\r\n'
        ":done\r\n"
        '(goto) 2>nul & del "%~f0"\r\n'
    )


def install_and_restart(downloaded: Path) -> None:
    """Windows only. Installed copy: run the new Setup quietly (it closes this app, upgrades it
    in place and reopens it). Portable copy: swap the file after this app exits."""
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    if is_installed():
        subprocess.Popen([str(downloaded), "/SILENT", "/CLOSEAPPLICATIONS", "/SUPPRESSMSGBOXES"],
                         creationflags=flags, env=env, close_fds=True)
        return
    bat = Path(tempfile.gettempdir()) / "autoclipper_update.bat"
    bat.write_text(windows_script(downloaded, Path(sys.executable)), encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, env=env, close_fds=True)
