import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.request
import os
import threading
import io

import pytest
from PIL import Image

from paraview_backend import is_paraview_available

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT_DIR / "test_data"
TEST_GRID = TEST_DATA_DIR / "square.vtk"
TEST_GRID_WITH_BOUNDARY = TEST_DATA_DIR / "square_with_boundary.vtk"
TEST_CUBE = TEST_DATA_DIR / "cube.vtk"
TEST_CUBE_WITH_BOUNDARY_ID = TEST_DATA_DIR / "cube_with_boundary_id.vtk"


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
        item = loc.nth(i)
        if not item.is_visible():
            continue
        text = item.inner_text().strip()
        hit = re.search(r"(\d+)\s+.*selected", text)
        if hit:
            matches.append(int(hit.group(1)))
    return matches[0] if matches else None


def _wait_for_selection_count(page, predicate, timeout_s=4):
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
    time.sleep(0.3)


def _open_create_field_dialog_from_select(page):
    _select_vselect_option(page, "Select field", "Create new...")
    page.wait_for_selector(
        "div.v-dialog--active:has-text('Create New Field')", timeout=40000
    )


def _create_new_edit_field(
    page, field_name, array_type="Cell data array", default_value="0"
):
    _open_create_field_dialog_from_select(page)
    if array_type:
        _select_vselect_option(page, "Array type", array_type)
    page.fill(
        "xpath=//label[contains(.,'Field name')]/ancestor::div[contains(@class,'v-input')]//input",
        field_name,
    )
    page.fill(
        "xpath=//label[contains(.,'Default value')]/ancestor::div[contains(@class,'v-input')]//input",
        default_value,
    )
    page.click("div.v-dialog--active button:has-text('Create')")
    page.wait_for_selector(
        "div.v-dialog--active:has-text('Create New Field')",
        state="hidden",
        timeout=40000,
    )
    time.sleep(0.4)


def _drag_normalized_box(page, view_box, rect, *, steps=12):
    fx0, fy0, fx1, fy1 = rect
    x0 = view_box["x"] + view_box["width"] * fx0
    y0 = view_box["y"] + view_box["height"] * fy0
    x1 = view_box["x"] + view_box["width"] * fx1
    y1 = view_box["y"] + view_box["height"] * fy1
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=steps)
    page.mouse.up()


def _switch_checked(page, label):
    switch = page.locator(
        f"xpath=//label[contains(normalize-space(.),'{label}')]/ancestor::div[contains(@class,'v-input')]"
    ).first
    switch.wait_for(state="visible", timeout=40000)
    classes = switch.get_attribute("class") or ""
    return "v-input--is-label-active" in classes


def _wait_for_switch_checked(page, label, checked, timeout_s=5):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _switch_checked(page, label) == checked:
            return
        time.sleep(0.1)
    assert _switch_checked(page, label) == checked


def _set_switch(page, label, checked):
    if _switch_checked(page, label) == checked:
        return
    page.click(f"label:has-text('{label}')")
    _wait_for_switch_checked(page, label, checked)


def _parse_env_box(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        return default
    try:
        return tuple(float(p) for p in parts)
    except ValueError:
        return default


def _foreground_bbox(
    png_bytes,
    *,
    threshold=245,
    margin=12,
    ignore_right_fraction=0.0,
):
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    width, height = image.size
    usable_width = max(margin, int(width * (1.0 - float(ignore_right_fraction))))
    background_pixels = []
    for x in range(usable_width):
        background_pixels.append(image.getpixel((x, 0)))
        background_pixels.append(image.getpixel((x, height - 1)))
    for y in range(1, height - 1):
        background_pixels.append(image.getpixel((0, y)))
        background_pixels.append(image.getpixel((usable_width - 1, y)))

    if background_pixels:
        bg_r = sorted(pixel[0] for pixel in background_pixels)[
            len(background_pixels) // 2
        ]
        bg_g = sorted(pixel[1] for pixel in background_pixels)[
            len(background_pixels) // 2
        ]
        bg_b = sorted(pixel[2] for pixel in background_pixels)[
            len(background_pixels) // 2
        ]
    else:
        bg_r = bg_g = bg_b = 255

    x0 = width
    y0 = height
    x1 = -1
    y1 = -1
    count = 0
    for y in range(margin, max(margin, height - margin)):
        for x in range(margin, max(margin, usable_width)):
            r, g, b = image.getpixel((x, y))
            background_delta = max(abs(r - bg_r), abs(g - bg_g), abs(b - bg_b))
            if min(r, g, b) < threshold and background_delta > 12:
                x0 = min(x0, x)
                y0 = min(y0, y)
                x1 = max(x1, x)
                y1 = max(y1, y)
                count += 1
    if count == 0:
        return None
    return {
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "width": x1 - x0 + 1,
        "height": y1 - y0 + 1,
        "count": count,
    }


def _wait_for_stable_viewport(viewport, *, timeout_s=8, poll_s=0.25):
    """Poll until two successive screenshots show no significant change.

    Returns the last screenshot once the render has settled.  Uses _changed_bbox
    as the comparator so minor rendering noise below its column-hit threshold is
    tolerated.
    """
    deadline = time.time() + timeout_s
    prev = viewport.screenshot()
    while time.time() < deadline:
        time.sleep(poll_s)
        curr = viewport.screenshot()
        if _changed_bbox(prev, curr) is None:
            return curr
        prev = curr
    return viewport.screenshot()


def _wait_for_foreground(
    viewport, *, ignore_right_fraction=0.0, timeout_s=8, narrower_than=None
):
    """Poll viewport screenshots until non-background content appears.

    When narrower_than is set, also requires bbox["width"] < narrower_than before
    returning — useful when the viewport already has content and we need to wait
    for it to shrink (e.g. hiding cells to show only faces).

    Returns (png_bytes, bbox). If the timeout expires, returns the last screenshot
    with whatever bbox was found (may be None or too wide).
    """
    deadline = time.time() + timeout_s
    while True:
        png = viewport.screenshot()
        bbox = _foreground_bbox(png, ignore_right_fraction=ignore_right_fraction)
        size_ok = narrower_than is None or (
            bbox is not None and bbox["width"] < narrower_than
        )
        if (bbox is not None and size_ok) or time.time() >= deadline:
            return png, bbox
        time.sleep(0.25)


def _changed_bbox(
    before_png_bytes,
    after_png_bytes,
    *,
    pixel_delta=16,
    margin=12,
    ignore_right_fraction=0.0,
):
    before = Image.open(io.BytesIO(before_png_bytes)).convert("RGB")
    after = Image.open(io.BytesIO(after_png_bytes)).convert("RGB")
    assert before.size == after.size
    width, height = before.size
    usable_width = max(margin, int(width * (1.0 - float(ignore_right_fraction))))
    col_counts = [0] * width
    row_counts = [0] * height
    x0 = width
    y0 = height
    x1 = -1
    y1 = -1
    count = 0
    for y in range(margin, max(margin, height - margin)):
        for x in range(margin, max(margin, usable_width)):
            br, bg, bb = before.getpixel((x, y))
            ar, ag, ab = after.getpixel((x, y))
            if max(abs(ar - br), abs(ag - bg), abs(ab - bb)) > pixel_delta:
                col_counts[x] += 1
                row_counts[y] += 1
                count += 1
    if count == 0:
        return None

    min_col_hits = max(4, int((height - 2 * margin) * 0.04))
    min_row_hits = max(2, int((width - 2 * margin) * 0.005))
    active_cols = [
        x
        for x in range(margin, max(margin, usable_width))
        if col_counts[x] >= min_col_hits
    ]
    active_rows = [
        y
        for y in range(margin, max(margin, height - margin))
        if row_counts[y] >= min_row_hits
    ]

    if not active_cols or not active_rows:
        return None

    x0 = min(active_cols)
    x1 = max(active_cols)
    y0 = min(active_rows)
    y1 = max(active_rows)
    return {
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "width": x1 - x0 + 1,
        "height": y1 - y0 + 1,
        "count": count,
    }


def _stream_proc_stdout(proc, echo=False):
    """Drain subprocess stdout, optionally echoing it for local diagnostics."""
    stream = getattr(proc, "stdout", None)
    if stream is None:
        return
    for line in stream:
        if echo:
            print(line, end="", flush=True)


def _drain_proc_stdout(proc):
    echo = os.environ.get("E2E_STREAM_APP_LOGS", "0").strip() in {
        "1",
        "true",
        "True",
    }
    threading.Thread(target=_stream_proc_stdout, args=(proc, echo), daemon=True).start()


def test_paraview_edit_pick_mode_click_and_box_selection_headless(shared_browser):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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

        assert _selection_count(page) == 0

        page.click("button:has-text('Select All')")
        all_count = _wait_for_selection_count(page, lambda count: count > 1)
        assert all_count is not None and all_count > 1

        view = page.locator('[style*="cursor: crosshair"]').first
        box = view.bounding_box()
        assert (
            box is not None and box["x"] >= 0 and box["width"] > 0 and box["height"] > 0
        )

        x_click = box["x"] + box["width"] * 0.5
        y_click = box["y"] + box["height"] * 0.5
        page.mouse.click(x_click, y_click)
        click_count = _wait_for_selection_count(
            page, lambda count: 0 < count < all_count
        )
        assert click_count is not None and 0 < click_count < all_count

        page.click("button:has-text('Clear All')")
        assert _wait_for_selection_count(page, lambda count: count == 0) == 0

        x0 = box["x"] + box["width"] * 0.35
        y0 = box["y"] + box["height"] * 0.35
        x1 = box["x"] + box["width"] * 0.52
        y1 = box["y"] + box["height"] * 0.49
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x1, y1, steps=12)
        page.mouse.up()
        box_count = _wait_for_selection_count(page, lambda count: count > 0)
        assert box_count is not None and box_count > 0

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_display_color_scale_visibility_survives_rescale(shared_browser):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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
        page.wait_for_selector("text=Display", timeout=40000)

        _select_vselect_option(page, "Color by", "MaterialID")
        page.wait_for_selector("text=Color Bar", timeout=40000)

        _wait_for_switch_checked(page, "Show color scale", True)

        _set_switch(page, "Show color scale", False)
        assert _switch_checked(page, "Show color scale") is False
        page.click("button:has-text('Rescale Data')")
        time.sleep(0.8)
        assert _switch_checked(page, "Show color scale") is False

        _set_switch(page, "Show color scale", True)
        assert _switch_checked(page, "Show color scale") is True
        page.click("button:has-text('Rescale Data')")
        time.sleep(0.8)
        assert _switch_checked(page, "Show color scale") is True

        _set_switch(page, "Show orientation axes", False)
        assert _switch_checked(page, "Show orientation axes") is False
        _set_switch(page, "Show orientation axes", True)
        assert _switch_checked(page, "Show orientation axes") is True

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_display_color_scale_visibility_survives_categorical_toggle(
    shared_browser,
):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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
        page.wait_for_selector("text=Display", timeout=40000)

        _select_vselect_option(page, "Color by", "MaterialID")
        page.wait_for_selector("text=Color Bar", timeout=40000)

        # Color scale starts visible; categorical coloring starts off.
        # Use polling waits — state updates arrive asynchronously after the selector.
        _wait_for_switch_checked(page, "Show color scale", True, timeout_s=8)
        _wait_for_switch_checked(
            page, "Interpret values as categories", False, timeout_s=8
        )

        # Hide the color scale, then toggle categorical on — must stay hidden
        _set_switch(page, "Show color scale", False)
        assert _switch_checked(page, "Show color scale") is False
        _set_switch(page, "Interpret values as categories", True)
        time.sleep(0.5)
        assert _switch_checked(page, "Show color scale") is False

        # Toggle categorical back off — must still stay hidden
        _set_switch(page, "Interpret values as categories", False)
        time.sleep(0.5)
        assert _switch_checked(page, "Show color scale") is False

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_categorical_annotations_updated_on_file_switch(shared_browser):
    """Categorical color annotations must be rebuilt for the new file's values.

    Regression: ParaView caches the MaterialID LUT globally. After enabling categorical
    on file A (IDs 1,2) and then loading file B (IDs 3,4,5), apply_coloring reused the
    cached LUT without calling _configure_categorical_lookup_table, leaving stale
    annotations from file A. The render was only corrected after a manual toggle.
    """
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

    port = _free_tcp_port()
    url = f"http://127.0.0.1:{port}"
    file_a = TEST_DATA_DIR / "square_mat_12.vtk"
    file_b = TEST_DATA_DIR / "square_mat_345.vtk"
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
            str(file_a),
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
        page.wait_for_selector("text=Display", timeout=40000)

        # File A: select MaterialID, enable categorical — LUT gets annotations [1, 2]
        _select_vselect_option(page, "Color by", "MaterialID")
        page.wait_for_selector("text=Color Bar", timeout=40000)
        _set_switch(page, "Interpret values as categories", True)
        time.sleep(0.8)

        # Open file B (IDs 3, 4, 5) via the remote browser — no file copy, no uploads dir
        page.click("button:has-text('Open Remote')")
        page.wait_for_selector("div.v-dialog--active", timeout=10000)
        page.click(
            f"div.v-dialog--active div.v-list-item__title:has-text('{file_b.name}')"
        )
        time.sleep(2.0)

        # Re-select MaterialID on file B — LUT is cached with InterpretValuesAsCategories=1
        _select_vselect_option(page, "Color by", "MaterialID")
        page.wait_for_selector("text=Color Bar", timeout=40000)
        time.sleep(1.0)
        assert _switch_checked(page, "Interpret values as categories") is True

        # Screenshot immediately after selection — annotations must already reflect file B
        viewport = page.locator(".coral-main-viewport")
        file_b_immediate_png = viewport.screenshot()

        # Toggle categorical off then on to force _configure_categorical_lookup_table
        _set_switch(page, "Interpret values as categories", False)
        time.sleep(0.5)
        _set_switch(page, "Interpret values as categories", True)
        time.sleep(0.8)

        file_b_after_toggle_png = viewport.screenshot()

        # Regression check: if annotations were stale the toggle would change the render.
        # With the fix the render is identical before and after the toggle.
        assert _changed_bbox(file_b_immediate_png, file_b_after_toggle_png) is None, (
            "Categorical annotations were stale after file switch — "
            "the color bar only became correct after a manual toggle"
        )

        # Pipeline node switch: verify set_active_node re-populates annotations.
        # selected_array stays "cell:MaterialID" on both nodes so on_array_change
        # does not fire — only set_active_node → _refresh_categorical_annotations
        # handles the LUT update.

        page.click(f"div.v-list-item__title:has-text('{file_a.name}')")
        _wait_for_switch_checked(
            page, "Interpret values as categories", True, timeout_s=8
        )
        time.sleep(1.0)
        file_a_switch_png = _wait_for_stable_viewport(viewport)

        _set_switch(page, "Interpret values as categories", False)
        time.sleep(0.5)
        _set_switch(page, "Interpret values as categories", True)
        file_a_after_toggle_png = _wait_for_stable_viewport(viewport)

        assert (
            _changed_bbox(file_a_switch_png, file_a_after_toggle_png) is None
        ), "Categorical annotations were stale after switching to file A in pipeline"

        page.click(f"div.v-list-item__title:has-text('{file_b.name}')")
        _wait_for_switch_checked(
            page, "Interpret values as categories", True, timeout_s=8
        )
        time.sleep(1.0)
        file_b_switch_png = _wait_for_stable_viewport(viewport)

        _set_switch(page, "Interpret values as categories", False)
        time.sleep(0.5)
        _set_switch(page, "Interpret values as categories", True)
        file_b_switch_after_toggle_png = _wait_for_stable_viewport(viewport)

        assert (
            _changed_bbox(file_b_switch_png, file_b_switch_after_toggle_png) is None
        ), "Categorical annotations were stale after switching back to file B in pipeline"

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_show_faces_only_keeps_explicit_left_boundary_cells(shared_browser):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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
            str(TEST_GRID_WITH_BOUNDARY),
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
        page.wait_for_selector("text=Display", timeout=40000)
        page.wait_for_selector(".coral-main-viewport", timeout=40000)

        _select_vselect_option(page, "Color by", "BoundaryID")
        _set_switch(page, "Show color scale", False)
        _set_switch(page, "Show orientation axes", False)
        _set_switch(page, "Show cells", True)
        _set_switch(page, "Show faces", True)
        time.sleep(1.0)

        viewport = page.locator(".coral-main-viewport")
        _set_switch(page, "Show cells", False)
        _set_switch(page, "Show faces", False)
        time.sleep(1.0)
        empty_png = viewport.screenshot()
        empty_bbox = _foreground_bbox(empty_png, ignore_right_fraction=0.15)
        assert empty_bbox is None

        _set_switch(page, "Show cells", True)
        _set_switch(page, "Show faces", True)
        _, full_bbox = _wait_for_foreground(viewport, ignore_right_fraction=0.15)
        assert full_bbox is not None
        assert full_bbox["width"] > 100
        assert full_bbox["height"] > 100

        _set_switch(page, "Show cells", False)
        _set_switch(page, "Show faces", True)
        _, faces_bbox = _wait_for_foreground(
            viewport,
            ignore_right_fraction=0.15,
            narrower_than=full_bbox["width"] * 0.5,
        )
        assert faces_bbox is not None
        assert faces_bbox["height"] >= full_bbox["height"] * 0.30
        assert faces_bbox["width"] <= full_bbox["width"] * 0.18
        assert faces_bbox["x1"] <= full_bbox["x0"] + full_bbox["width"] * 0.32
        assert (faces_bbox["x0"] + faces_bbox["x1"]) / 2.0 <= full_bbox[
            "x0"
        ] + full_bbox["width"] * 0.24

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_show_faces_only_keeps_explicit_cube_boundary_faces(shared_browser):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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
            str(TEST_CUBE_WITH_BOUNDARY_ID),
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
        page.wait_for_selector("text=Display", timeout=40000)
        page.wait_for_selector(".coral-main-viewport", timeout=40000)

        _select_vselect_option(page, "Color by", "BoundaryID")
        _set_switch(page, "Show color scale", False)
        _set_switch(page, "Show orientation axes", False)
        _set_switch(page, "Show cells", False)
        _set_switch(page, "Show faces", False)
        time.sleep(1.0)

        viewport = page.locator(".coral-main-viewport")
        empty_png = viewport.screenshot()

        _set_switch(page, "Show faces", True)
        time.sleep(1.0)

        faces_bbox = _changed_bbox(
            empty_png,
            viewport.screenshot(),
            ignore_right_fraction=0.15,
        )
        assert faces_bbox is not None
        assert faces_bbox["width"] > 50
        assert faces_bbox["height"] > 50
        assert faces_bbox["count"] > 500

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_point_field_replace_box_selection_does_not_toggle_overlap(
    shared_browser,
):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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

        _create_new_edit_field(
            page,
            "TestField",
            array_type="Point data array",
            default_value="0",
        )
        page.wait_for_selector("text=TestField", timeout=40000)
        page.click("button:has-text('Pick')")
        _select_vselect_option(page, "Selection mode", "Replace")

        view = page.locator('[style*="cursor: crosshair"]').first
        box = view.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] > 0

        first_rect = (0.553663, 0.434707, 0.757133, 0.54557)
        second_rect = (0.2356, 0.414752, 0.813425, 0.561162)

        page.click("button:has-text('Clear All')")
        assert _wait_for_selection_count(page, lambda count: count == 0) == 0
        _drag_normalized_box(page, box, second_rect)
        expected_second_count = _wait_for_selection_count(
            page, lambda count: count > 0, timeout_s=8
        )
        assert expected_second_count is not None and expected_second_count > 0

        page.click("button:has-text('Clear All')")
        assert _wait_for_selection_count(page, lambda count: count == 0) == 0
        _drag_normalized_box(page, box, first_rect)
        first_count = _wait_for_selection_count(
            page, lambda count: count > 0, timeout_s=8
        )
        assert first_count is not None and first_count > 0

        _drag_normalized_box(page, box, second_rect)
        replace_count = _wait_for_selection_count(
            page, lambda count: count == expected_second_count, timeout_s=8
        )
        assert replace_count == expected_second_count, (
            "Replace mode should discard the previous point selection before applying "
            f"the second box. first={first_count}, expected_second={expected_second_count}, "
            f"actual={_selection_count(page)}"
        )

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_surface_mode_select_left_boundary_apply_boundaryid_and_save(
    shared_browser,
):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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

        geometry_mode = page.locator(
            "div.v-input:has(label:has-text('Geometry mode'))"
        ).first
        geometry_mode.click()
        page.click("div.v-list-item__title:has-text('Surface')")
        time.sleep(0.4)

        _create_new_edit_field(
            page,
            "BoundaryID",
            array_type="Cell data array",
            default_value="1",
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
            page.click("button:has-text('Clear All')")
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
                page.click("button:has-text('Clear All')")
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

        page.fill(
            "xpath=//label[contains(.,'Value / Calculator')]/ancestor::div[contains(@class,'v-input')]//input",
            "1",
        )
        page.click("button:has-text('Assign to Selected')")

        page.click("button:has-text('Save Edit Result')")
        filename_input = page.locator(
            "xpath=//label[contains(.,'Output filename')]/ancestor::div[contains(@class,'v-input')]//input"
        )
        filename_input.wait_for(state="visible", timeout=10000)
        filename_input.fill(output_name)
        resolved_name = filename_input.input_value().strip() or output_name
        resolved_path = TEST_DATA_DIR / resolved_name
        page.locator(".v-dialog--active button:has-text('Save')").click()
        save_status = page.locator("text=Saved edited dataset to")
        save_status.wait_for(state="visible", timeout=40000)
        status_text = save_status.last.inner_text().strip()
        match = re.search(r"Saved edited dataset to\s+(.+)$", status_text)
        status_name = match.group(1).strip() if match else resolved_name
        status_path = TEST_DATA_DIR / status_name
        deadline = time.time() + 40
        while (
            time.time() < deadline
            and not resolved_path.exists()
            and not status_path.exists()
        ):
            time.sleep(0.25)

        final_path = status_path if status_path.exists() else resolved_path
        assert final_path.exists()
        assert final_path.stat().st_size > 0
        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        for path in {
            output_path,
            TEST_DATA_DIR / "new.vtu",
            TEST_DATA_DIR / "square_edited.vtu",
        }:
            if path.exists():
                path.unlink()


def test_paraview_cube_surface_selection_assigns_created_cell_field(shared_browser):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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
            str(TEST_CUBE),
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

        _create_new_edit_field(
            page,
            "BoundaryID",
            array_type="Cell data array",
            default_value="0",
        )

        _select_vselect_option(page, "Geometry mode", "Surface")

        view = page.locator('[style*="cursor: crosshair"]').first
        box = view.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] > 0

        selected_count = 0
        for fx, fy in ((0.50, 0.50), (0.40, 0.42), (0.60, 0.42), (0.42, 0.58)):
            page.click("button:has-text('Clear All')")
            time.sleep(0.3)
            page.mouse.click(
                box["x"] + box["width"] * fx,
                box["y"] + box["height"] * fy,
            )
            selected = _wait_for_selection_count(page, lambda count: count > 0)
            selected_count = selected or 0
            if selected_count > 0:
                break

        assert selected_count > 0

        page.fill(
            "xpath=//label[contains(.,'Value / Calculator')]/ancestor::div[contains(@class,'v-input')]//input",
            "1",
        )
        page.click("button:has-text('Assign to Selected')")
        page.wait_for_selector(
            "text=Assigned 'BoundaryID' on",
            state="visible",
            timeout=40000,
        )
        assert page.locator("text=Edit apply failed").count() == 0

        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_paraview_surface_mode_grow_left_edge_with_zero_angle(shared_browser):
    if not is_paraview_available():
        pytest.skip("Warning test skipped: ParaView is not installed")

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
        page.click("button:has-text('Pick')")
        time.sleep(0.2)

        geometry_mode = page.locator(
            "div.v-input:has(label:has-text('Geometry mode'))"
        ).first
        geometry_mode.click()
        page.click("div.v-list-item__title:has-text('Surface')")
        time.sleep(0.4)

        # Enable grow and force angle threshold to 0° through the slider.
        page.click("label:has-text('Grow selection')")
        time.sleep(0.2)
        slider = page.locator(
            "xpath=//div[contains(@class,'v-list-item__content')][.//div[contains(normalize-space(.),'Grow angle')]]//div[contains(@class,'v-slider')]"
        ).first
        slider.wait_for(state="visible", timeout=40000)
        slider_box = slider.bounding_box()
        assert slider_box is not None and slider_box["width"] > 0
        page.mouse.click(
            slider_box["x"] + 2,
            slider_box["y"] + slider_box["height"] * 0.5,
        )
        time.sleep(0.3)

        view = page.locator('[style*="cursor: crosshair"]').first
        box = view.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] > 0

        attempts = []
        manual_mode = os.environ.get("E2E_SURFACE_GROW_MANUAL", "0").strip() in {
            "1",
            "true",
            "True",
        }

        def _try_click(fx, fy, label):
            page.click("button:has-text('Clear All')")
            time.sleep(0.35)
            x = box["x"] + box["width"] * fx
            y = box["y"] + box["height"] * fy
            page.mouse.click(x, y)
            count = _wait_for_selection_count(page, lambda value: value > 0)
            print(
                f"[grow-e2e] click {label}: fx=({fx:.3f},{fy:.3f}) "
                f"px=({x:.1f},{y:.1f}) count={count}",
                flush=True,
            )
            attempts.append(
                {
                    "kind": "click",
                    "label": label,
                    "fx": fx,
                    "fy": fy,
                    "x": x,
                    "y": y,
                    "count": count,
                }
            )
            return count or 0

        def _try_box(fx0, fy0, fx1, fy1, label):
            page.click("button:has-text('Clear All')")
            time.sleep(0.35)
            x0 = box["x"] + box["width"] * fx0
            y0 = box["y"] + box["height"] * fy0
            x1 = box["x"] + box["width"] * fx1
            y1 = box["y"] + box["height"] * fy1
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=10)
            page.mouse.up()
            count = _wait_for_selection_count(page, lambda value: value > 0)
            print(
                f"[grow-e2e] box {label}: fx=({fx0:.3f},{fy0:.3f})->({fx1:.3f},{fy1:.3f}) "
                f"px=({x0:.1f},{y0:.1f})->({x1:.1f},{y1:.1f}) count={count}",
                flush=True,
            )
            attempts.append(
                {
                    "kind": "box",
                    "label": label,
                    "fx0": fx0,
                    "fy0": fy0,
                    "fx1": fx1,
                    "fy1": fy1,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "count": count,
                }
            )
            return count or 0

        selected = 0
        if manual_mode:
            page.click("button:has-text('Clear All')")
            time.sleep(0.35)
            page.evaluate(
                """
            () => {
              window.__e2eManualDrag = null;
              window.__e2eManualStart = null;
              const onDown = (e) => {
                window.__e2eManualStart = {
                  x: e.clientX,
                  y: e.clientY,
                };
              };
              const onUp = (e) => {
                const s = window.__e2eManualStart;
                if (!s) return;
                if (Math.abs(e.clientX - s.x) < 3 && Math.abs(e.clientY - s.y) < 3) {
                  return;
                }
                window.__e2eManualDrag = {
                  x0: s.x,
                  y0: s.y,
                  x1: e.clientX,
                  y1: e.clientY,
                };
              };
              document.addEventListener('mousedown', onDown, true);
              document.addEventListener('mouseup', onUp, true);
              window.__e2eManualCleanup = () => {
                document.removeEventListener('mousedown', onDown, true);
                document.removeEventListener('mouseup', onUp, true);
              };
            }
            """,
            )
            print(
                "[grow-e2e] manual mode active: perform click/drag selection now...",
                flush=True,
            )
            deadline = time.time() + 30
            manual_drag = None
            while time.time() < deadline:
                selected = _selection_count(page) or 0
                manual_drag = page.evaluate("() => window.__e2eManualDrag || null")
                if selected >= 4 and manual_drag:
                    break
                time.sleep(0.2)
            page.evaluate(
                "() => { if (window.__e2eManualCleanup) window.__e2eManualCleanup(); }"
            )
            if manual_drag:
                fx0 = (float(manual_drag["x0"]) - box["x"]) / box["width"]
                fy0 = (float(manual_drag["y0"]) - box["y"]) / box["height"]
                fx1 = (float(manual_drag["x1"]) - box["x"]) / box["width"]
                fy1 = (float(manual_drag["y1"]) - box["y"]) / box["height"]
                print(
                    "[grow-e2e] manual recorded box: "
                    f"E2E_SURFACE_GROW_BOX={fx0:.6f},{fy0:.6f},{fx1:.6f},{fy1:.6f}",
                    flush=True,
                )
            else:
                print(
                    "[grow-e2e] manual recorder did not capture a drag inside view.",
                    flush=True,
                )
                assert (
                    selected >= 4
                ), f"Manual grow selection expected >=4, got {selected}. Attempts: {attempts}"
                context.close()
                return

        # Deterministic box: can be overridden from env for local calibration.
        fx0, fy0, fx1, fy1 = _parse_env_box(
            "E2E_SURFACE_GROW_BOX",
            (0.146393, 0.412025, 0.425668, 0.473942),
        )
        flip_y = os.environ.get("E2E_SURFACE_GROW_FLIP_Y", "0").strip() in {
            "1",
            "true",
            "True",
        }
        if flip_y:
            fy0, fy1 = 1.0 - fy0, 1.0 - fy1
        selected = _try_box(fx0, fy0, fx1, fy1, "deterministic-box")
        if selected < 4:
            selected = _try_box(
                fx0, 1.0 - fy0, fx1, 1.0 - fy1, "deterministic-box-flipy"
            )
        if selected < 4:
            cx = (fx0 + fx1) * 0.5
            cy = (fy0 + fy1) * 0.5
            selected = _try_click(cx, cy, "deterministic-center-click")

        assert selected >= 4, (
            f"Expected grow selection >=4, got {selected}. "
            f"box=({fx0:.3f},{fy0:.3f},{fx1:.3f},{fy1:.3f}), flip_y={flip_y}. Attempts: {attempts}"
        )
        context.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
