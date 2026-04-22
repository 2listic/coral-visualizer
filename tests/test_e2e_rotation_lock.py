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

def test_paraview_pick_mode_does_not_rotate_on_drag():
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
            "-u", # Unbuffered output
            "app.py",
            "--backend",
            "paraview",
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
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1200, "height": 800})
            page.goto(url, wait_until="domcontentloaded")
            
            # Wait for app to be ready
            page.wait_for_selector("button:has-text('Enter Edit Mode')", timeout=40000)
            
            # Helper to get camera position via trame state or a custom trigger if we can.
            # Since we exposed ctrl.pv_backend, we might be able to use a trigger.
            def get_camera_pos():
                # We use a trick: ParaViewBackend.view.GetActiveCamera().GetPosition()
                # We can try to use a trame trigger if we register one, or just use the screenshot for now but with a more robust way.
                # Actually, let's use the screenshot but I will PRINT the diff if it fails.
                return page.evaluate("() => { return 0; }") # Placeholder

            # Enter Edit Mode (defaults to Pick mode)
            page.click("button:has-text('Enter Edit Mode')")
            page.wait_for_selector("text=Edit Tools", timeout=40000)

            # Clear any initial selection to have a clean state
            page.click("button:has-text('Clear Selection')")
            time.sleep(1.0)
            
            # Click in a safe place to remove hover state from buttons
            page.mouse.click(10, 10)
            time.sleep(0.5)

            # Take a screenshot BEFORE any drag (only of the viewport)
            viewport = page.locator(".coral-main-viewport")
            screenshot_initial = viewport.screenshot()
            
            # --- PHASE 1: DRAG IN PICK MODE ---
            # Perform a drag that WOULD rotate if not locked
            box = viewport.bounding_box()
            x0 = box["x"] + box["width"] * 0.3
            y0 = box["y"] + box["height"] * 0.3
            x1 = box["x"] + box["width"] * 0.7
            y1 = box["y"] + box["height"] * 0.7
            
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=20)
            page.mouse.up()
            
            time.sleep(1.0) # Wait for any potential (but unwanted) rotation
            
            # Clear selection AGAIN to remove highlight from the drag we just did
            page.click("button:has-text('Clear Selection')")
            time.sleep(1.0)
            
            # Click in a safe place to remove hover state from buttons
            page.mouse.click(10, 10)
            time.sleep(0.5)
            
            screenshot_after_pick_drag = viewport.screenshot()
            
            # PHASE 1 ASSERT: Should NOT have rotated.
            assert screenshot_initial == screenshot_after_pick_drag, "Screenshots differ! The view likely rotated or changed during drag in PICK mode."

            # --- PHASE 2: DRAG IN ROTATE MODE ---
            # Switch to Rotate mode
            page.click("button:has-text('Rotate')")
            time.sleep(1.0)
            
            page.mouse.click(10, 10) # Remove hover
            time.sleep(0.5)
            
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=20)
            page.mouse.up()
            
            time.sleep(1.5) # Wait for rotation to render
            
            screenshot_after_rotate_drag = viewport.screenshot()
            
            # PHASE 2 ASSERT: SHOULD have rotated.
            assert screenshot_after_pick_drag != screenshot_after_rotate_drag, "Screenshots are identical! The view did NOT rotate during drag in ROTATE mode."

            browser.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
