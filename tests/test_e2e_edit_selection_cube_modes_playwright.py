import pathlib
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import threading

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


def _stream_proc_stdout(proc):
    stream = getattr(proc, "stdout", None)
    if stream is None:
        return
    echo = os.environ.get("E2E_STREAM_APP_LOGS", "0").strip() in {"1", "true", "True"}
    for line in stream:
        if echo or "[selection-debug]" in line:
            print(line, end="", flush=True)


def _drain_proc_stdout(proc):
    threading.Thread(target=_stream_proc_stdout, args=(proc,), daemon=True).start()


def _selection_count(page):
    loc = page.locator(
        "xpath=//div[contains(@class,'v-list-item__title') and contains(.,'selected')]"
    )
    matches = []
    for i in range(loc.count()):
        item = loc.nth(i)
        if not item.is_visible():
            continue
        text = item.inner_text().strip()
        hit = re.search(r"(\d+)\s+.*selected", text)
        if hit:
            matches.append(int(hit.group(1)))
    return matches[0] if matches else None


def _wait_for_selection_count(page, predicate, timeout_s=5):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = _selection_count(page)
        if last is not None and predicate(last):
            return last
        time.sleep(0.1)
    return last


def _select_vselect_option(page, label, option):
    selector = page.locator(f"div.v-input:has(label:has-text('{label}'))").first
    selector.click()
    page.click(f"div.v-list-item__title:has-text('{option}')")
    time.sleep(0.35)


def _create_new_point_field(page, field_name):
    _select_vselect_option(page, "Select field", "Create new...")
    page.wait_for_selector(
        "div.v-dialog--active:has-text('Create New Field')", timeout=40000
    )
    _select_vselect_option(page, "Array type", "Point data array")
    page.fill(
        "xpath=//label[contains(.,'Field name')]/ancestor::div[contains(@class,'v-input')]//input",
        field_name,
    )
    page.fill(
        "xpath=//label[contains(.,'Default value')]/ancestor::div[contains(@class,'v-input')]//input",
        "0",
    )
    page.click("div.v-dialog--active button:has-text('Create')")
    page.wait_for_selector(
        "div.v-dialog--active:has-text('Create New Field')",
        state="hidden",
        timeout=40000,
    )
    time.sleep(0.4)


def _drag_center_box(page, view_box):
    x0 = view_box["x"] + view_box["width"] * 0.43
    y0 = view_box["y"] + view_box["height"] * 0.43
    x1 = view_box["x"] + view_box["width"] * 0.57
    y1 = view_box["y"] + view_box["height"] * 0.57
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=12)
    page.mouse.up()


@pytest.mark.parametrize(
    "mode_label,requires_point_field",
    [
        ("Volume", False),
        ("Surface", False),
        ("Point", True),
    ],
)
def test_paraview_cube_center_box_selection_in_available_edit_modes(
    shared_browser, mode_label, requires_point_field
):
    if not is_paraview_available():
        pytest.skip("ParaView backend is not available in this environment")
    if not TEST_GRID.exists():
        pytest.skip(f"Missing required test dataset: {TEST_GRID}")

    port = _free_tcp_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            sys.executable,
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _drain_proc_stdout(proc)

    try:
        _wait_for_http_ready(url)
        context = shared_browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("button:has-text('Enter Edit Mode')", timeout=40000)

        page.click("button:has-text('Enter Edit Mode')")
        page.wait_for_selector("text=Edit Tools", timeout=40000)
        time.sleep(1.0)

        _select_vselect_option(page, "Selection behavior", "Touch")

        if requires_point_field:
            _create_new_point_field(page, "E2EPointField")
        else:
            _select_vselect_option(page, "Geometry mode", mode_label)

        page.click("button:has-text('Clear Selection')")
        assert _wait_for_selection_count(page, lambda count: count == 0) == 0

        view = page.locator('[style*="cursor: crosshair"]').first
        box = view.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] > 0

        _drag_center_box(page, box)
        selected = _wait_for_selection_count(page, lambda count: count > 0, timeout_s=6)
        assert (
            selected is not None and selected > 0
        ), f"Center box selection returned no entities in mode={mode_label}"

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
