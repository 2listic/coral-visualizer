import pathlib
import socket
import subprocess
import sys
import time
import urllib.request
import pytest
from paraview_backend import is_paraview_available

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT_DIR / "test_data"
TEST_GRID = TEST_DATA_DIR / "cube.vtk"


def _free_tcp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


def _wait_for_http_ready(url, timeout_s=45):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for server at {url}")


def test_paraview_non_edit_mode_rotates_on_drag(shared_browser):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

    port = _free_tcp_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "app.py",
            "--backend",
            "paraview",
            "--server",
            "--data-directory",
            str(TEST_DATA_DIR),
            "--file",
            str(TEST_GRID),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT_DIR,
        stdout=sys.stdout,
        stderr=sys.stderr,
        text=True,
    )

    try:
        _wait_for_http_ready(url)
        context = shared_browser.new_context(viewport={"width": 1200, "height": 800})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        page.wait_for_selector(".coral-main-viewport", timeout=40000)
        viewport = page.locator(".coral-main-viewport")
        screenshot_initial = viewport.screenshot()

        box = viewport.bounding_box()
        x0 = box["x"] + box["width"] * 0.3
        y0 = box["y"] + box["height"] * 0.3
        x1 = box["x"] + box["width"] * 0.7
        y1 = box["y"] + box["height"] * 0.7

        # Drag to rotate
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=20)
        page.mouse.up()

        time.sleep(1.5)  # Wait for rotation render

        screenshot_after_rotate_drag = viewport.screenshot()

        assert (
            screenshot_initial != screenshot_after_rotate_drag
        ), "Screenshots are identical! The view did NOT rotate during drag in non-edit mode."

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
