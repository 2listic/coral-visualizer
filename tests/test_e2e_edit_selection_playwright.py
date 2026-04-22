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


def test_paraview_edit_pick_mode_click_and_box_selection_headless(shared_browser):
    if not is_paraview_available():
        pytest.skip("ParaView backend is not available in this environment")

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
        context = shared_browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
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

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_surface_mode_select_left_boundary_apply_boundaryid_and_save(shared_browser):
    if not is_paraview_available():
        pytest.skip("ParaView backend is not available in this environment")

    output_name = "e2e_surface_boundaryid_left.vtu"
    output_path = TEST_DATA_DIR / output_name
    if output_path.exists():
        output_path.unlink()

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
        context = shared_browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("button:has-text('Enter Edit Mode')", timeout=40000)

        page.click("button:has-text('Enter Edit Mode')")
        page.wait_for_selector("text=Edit Tools", timeout=40000)
        time.sleep(1.0)

        geometry_mode = page.locator("div.v-input:has(label:has-text('Geometry mode'))").first
        geometry_mode.click()
        page.click("div.v-list-item__title:has-text('Surface')")
        time.sleep(0.4)

        page.fill(
            "xpath=//label[contains(.,'Field name')]/ancestor::div[contains(@class,'v-input')]//input",
            "BoundaryID",
        )
        page.fill(
            "xpath=//label[contains(.,'Default value')]/ancestor::div[contains(@class,'v-input')]//input",
            "1",
        )

        view = page.locator('[style*="cursor: crosshair"]').first
        box = view.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] > 0

        def selected_total():
            count = _selection_count(page)
            if count:
                return count
            alerts = page.locator("text=selected total")
            if alerts.count() == 0:
                return 0
            text = alerts.last.inner_text().strip()
            hit = re.search(r"(\d+)\s+selected total", text)
            return int(hit.group(1)) if hit else 0

        selected_count = 0
        left_boxes = [
            (0.03, 0.18, 0.62, 0.86),
            (0.08, 0.24, 0.55, 0.78),
            (0.15, 0.28, 0.50, 0.70),
        ]
        for fx0, fy0, fx1, fy1 in left_boxes:
            page.click("button:has-text('Clear Selection')")
            time.sleep(0.5)
            x0 = box["x"] + box["width"] * fx0
            y0 = box["y"] + box["height"] * fy0
            x1 = box["x"] + box["width"] * fx1
            y1 = box["y"] + box["height"] * fy1
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=12)
            page.mouse.up()
            time.sleep(0.9)
            selected_count = selected_total()
            if selected_count > 0:
                break

        if selected_count == 0:
            left_clicks = [(0.20, 0.50), (0.28, 0.46), (0.24, 0.58), (0.34, 0.52)]
            for fx, fy in left_clicks:
                page.click("button:has-text('Clear Selection')")
                time.sleep(0.4)
                page.mouse.click(
                    box["x"] + box["width"] * fx,
                    box["y"] + box["height"] * fy,
                )
                time.sleep(0.8)
                selected_count = selected_total()
                if selected_count > 0:
                    break

        assert selected_count > 0

        page.click("button:has-text('Apply Edit')")

        page.fill(
            "xpath=//label[contains(.,'Output filename')]/ancestor::div[contains(@class,'v-input')]//input",
            output_name,
        )
        page.click("button:has-text('Save Edit Result')")
        page.wait_for_selector(f"text=Saved edited dataset to {output_name}", timeout=40000)

        assert output_path.exists()
        assert output_path.stat().st_size > 0
        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if output_path.exists():
            output_path.unlink()
