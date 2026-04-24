import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.request
import os
import threading

import pytest

from paraview_backend import is_paraview_available


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT_DIR / "test_data"
TEST_GRID = TEST_DATA_DIR / "square.vtk"


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
    return matches[-1] if matches else None


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


def _stream_proc_stdout(proc):
    """Stream subprocess stdout to current test stdout."""
    stream = getattr(proc, "stdout", None)
    if stream is None:
        return
    for line in stream:
        print(line, end="", flush=True)


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
    if os.environ.get("E2E_STREAM_APP_LOGS", "0").strip() in {"1", "true", "True"}:
        threading.Thread(target=_stream_proc_stdout, args=(proc,), daemon=True).start()

    try:
        _wait_for_http_ready(url)
        context = shared_browser.new_context(
            viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(
            "button:has-text('Enter Edit Mode')", timeout=40000)

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
        context = shared_browser.new_context(
            viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(
            "button:has-text('Enter Edit Mode')", timeout=40000)

        page.click("button:has-text('Enter Edit Mode')")
        page.wait_for_selector("text=Edit Tools", timeout=40000)
        time.sleep(1.0)

        geometry_mode = page.locator(
            "div.v-input:has(label:has-text('Geometry mode'))").first
        geometry_mode.click()
        page.click("div.v-list-item__title:has-text('Surface')")
        time.sleep(0.4)

        page.click("button:has-text('Create New Field')")
        page.wait_for_selector("text=Create New Field", timeout=40000)

        page.fill(
            "xpath=//label[contains(.,'Field name')]/ancestor::div[contains(@class,'v-input')]//input",
            "BoundaryID",
        )
        page.fill(
            "xpath=//label[contains(.,'Default value')]/ancestor::div[contains(@class,'v-input')]//input",
            "1",
        )
        page.click("div.v-dialog--active button:has-text('Create')")
        time.sleep(0.4)

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
            left_clicks = [(0.20, 0.50), (0.28, 0.46),
                           (0.24, 0.58), (0.34, 0.52)]
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

        page.fill(
            "xpath=//label[contains(.,'Value / Calculator')]/ancestor::div[contains(@class,'v-input')]//input",
            "1",
        )
        page.click("button:has-text('Assign to Selected')")

        page.fill(
            "xpath=//label[contains(.,'Output filename')]/ancestor::div[contains(@class,'v-input')]//input",
            output_name,
        )
        resolved_name = page.input_value(
            "xpath=//label[contains(.,'Output filename')]/ancestor::div[contains(@class,'v-input')]//input"
        ).strip() or output_name
        resolved_path = TEST_DATA_DIR / resolved_name
        page.click("button:has-text('Save Edit Result')")
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
        for path in {output_path, TEST_DATA_DIR / "new.vtu", TEST_DATA_DIR / "square_edited.vtu"}:
            if path.exists():
                path.unlink()


def test_paraview_surface_mode_grow_left_edge_with_zero_angle(shared_browser):
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
        context = shared_browser.new_context(
            viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(
            "button:has-text('Enter Edit Mode')", timeout=40000)

        page.click("button:has-text('Enter Edit Mode')")
        page.wait_for_selector("text=Edit Tools", timeout=40000)
        time.sleep(1.0)
        page.click("button:has-text('Pick')")
        time.sleep(0.2)

        geometry_mode = page.locator(
            "div.v-input:has(label:has-text('Geometry mode'))").first
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
            page.click("button:has-text('Clear Selection')")
            time.sleep(0.35)
            x = box["x"] + box["width"] * fx
            y = box["y"] + box["height"] * fy
            page.mouse.click(x, y)
            time.sleep(0.9)
            count = _selection_count(page)
            print(
                f"[grow-e2e] click {label}: fx=({fx:.3f},{fy:.3f}) "
                f"px=({x:.1f},{y:.1f}) count={count}",
                flush=True,
            )
            attempts.append({"kind": "click", "label": label,
                            "fx": fx, "fy": fy, "x": x, "y": y, "count": count})
            return count or 0

        def _try_box(fx0, fy0, fx1, fy1, label):
            page.click("button:has-text('Clear Selection')")
            time.sleep(0.35)
            x0 = box["x"] + box["width"] * fx0
            y0 = box["y"] + box["height"] * fy0
            x1 = box["x"] + box["width"] * fx1
            y1 = box["y"] + box["height"] * fy1
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=10)
            page.mouse.up()
            time.sleep(0.9)
            count = _selection_count(page)
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
            page.click("button:has-text('Clear Selection')")
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
                assert selected >= 4, (
                    f"Manual grow selection expected >=4, got {selected}. Attempts: {attempts}"
                )
                context.close()
                return

        # Deterministic box: can be overridden from env for local calibration.
        fx0, fy0, fx1, fy1 = _parse_env_box(
            "E2E_SURFACE_GROW_BOX",
            (0.146393, 0.412025, 0.425668, 0.473942),
        )
        flip_y = os.environ.get("E2E_SURFACE_GROW_FLIP_Y", "0").strip() in {"1", "true", "True"}
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
