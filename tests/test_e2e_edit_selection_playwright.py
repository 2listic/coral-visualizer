import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from paraview_backend import is_paraview_available


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT_DIR / "test_data"
TEST_GRID = TEST_DATA_DIR / "hyper_cube-2ref.vtk"


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


def _selection_count(page):
    loc = page.locator(
        "xpath=//div[contains(@class,'v-list-item__title') and contains(.,'selected')]"
    )
    matches = []
    for i in range(loc.count()):
        text = loc.nth(i).inner_text().strip()
        hit = re.search(r"(\d+)\s+.*selected", text)
        if hit:
            matches.append(int(hit.group(1)))
    return matches[0] if matches else None


def test_paraview_edit_pick_mode_click_and_box_selection_headless(show_browser):
    if not is_paraview_available():
        pytest.skip("ParaView backend is not available in this environment")

    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright is required for headless UI E2E tests",
    )
    sync_playwright = playwright.sync_playwright

    port = _free_tcp_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "app.py",
            "--backend",
            "paraview",
            "--no-browser",
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_for_http_ready(url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not show_browser)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1600, "height": 1000})
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("button:has-text('Enter Edit Mode')", timeout=40000)

            page.click("button:has-text('Enter Edit Mode')")
            page.wait_for_selector("text=Edit Tools", timeout=40000)
            time.sleep(1.0)

            assert _selection_count(page) == 0

            page.click("button:has-text('Select All')")
            time.sleep(0.8)
            all_count = _selection_count(page)
            assert all_count is not None and all_count > 1

            view = page.locator('[style*="cursor: crosshair"]').first
            box = view.bounding_box()
            assert box is not None and box["x"] >= 0 and box["width"] > 0 and box["height"] > 0

            x_click = box["x"] + box["width"] * 0.5
            y_click = box["y"] + box["height"] * 0.5
            page.mouse.click(x_click, y_click)
            time.sleep(1.0)
            click_count = _selection_count(page)
            assert click_count is not None and 0 < click_count < all_count

            page.click("button:has-text('Clear Selection')")
            time.sleep(0.8)
            assert _selection_count(page) == 0

            x0 = box["x"] + box["width"] * 0.35
            y0 = box["y"] + box["height"] * 0.35
            x1 = box["x"] + box["width"] * 0.52
            y1 = box["y"] + box["height"] * 0.49
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=12)
            page.mouse.up()
            time.sleep(1.2)
            box_count = _selection_count(page)
            assert box_count is not None and box_count > 0

            browser.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
