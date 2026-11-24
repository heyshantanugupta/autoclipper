from autoclipper.updates import is_newer


def test_is_newer():
    assert is_newer("0.1.2", "0.1.1")
    assert is_newer("0.2.0", "0.1.9")
    assert not is_newer("0.1.1", "0.1.1")
    assert not is_newer("0.1.0", "0.1.1")
    assert not is_newer("", "0.1.1")


def test_asset_names():
    from autoclipper.updates import asset_name
    assert asset_name("0.2.0", "win32") == "AutoClipper-0.2.0-windows-x64.exe"
    assert asset_name("0.2.0", "darwin", "arm64") == "AutoClipper-0.2.0-mac-arm64.zip"
    assert asset_name("0.2.0", "darwin", "x86_64") == "AutoClipper-0.2.0-mac-x64.zip"
    assert asset_name("0.2.0", "linux") is None


def test_mac_app_path():
    from pathlib import Path
    from autoclipper.updates import mac_app_path
    p = mac_app_path("/Applications/AutoClipper.app/Contents/MacOS/AutoClipper")
    assert p == Path("/Applications/AutoClipper.app")
    assert mac_app_path("/usr/bin/python3") is None


def test_scripts_mention_paths():
    from pathlib import Path
    from autoclipper.updates import mac_script, windows_script
    w = windows_script(Path("C:/t/new.exe"), Path("C:/Apps/AutoClipper.exe"))
    assert "new.exe" in w and "AutoClipper.exe" in w and "start" in w
    m = mac_script(Path("/tmp/u.zip"), Path("/Applications/AutoClipper.app"))
    assert str(Path("/Applications/AutoClipper.app")) in m and "open" in m and ".old" in m


def test_download_and_incomplete(tmp_path):
    import http.server, threading
    from autoclipper.updates import download
    d = tmp_path / "srv"
    d.mkdir()
    (d / "big.bin").write_bytes(b"x" * 2_000_000)
    (d / "small.bin").write_bytes(b"x" * 10)
    h = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(d), **k)
    srv = http.server.HTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    seen = []
    out = download(f"{base}/big.bin", tmp_path / "got.bin", seen.append)
    assert out.stat().st_size == 2_000_000 and seen and seen[-1] == 1.0
    import pytest
    with pytest.raises(RuntimeError):
        download(f"{base}/small.bin", tmp_path / "small.bin")
    srv.shutdown()
