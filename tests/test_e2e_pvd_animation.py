
import pathlib
import subprocess
import sys
import time
import socket
import urllib.request
import os
import threading
import re
import pytest
from paraview_backend import is_paraview_available

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT_DIR / "test_data"
ANIMATION_PVD = TEST_DATA_DIR / "animation.pvd"

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

@pytest.fixture
def paraview_server():
    if not is_paraview_available():
        pytest.skip("ParaView not available")
    
    port = _free_tcp_port()
    cmd = [
        sys.executable,
        str(ROOT_DIR / "app.py"),
        "--backend", "paraview",
        "--file", str(ANIMATION_PVD),
        "--data-directory", str(TEST_DATA_DIR),
        "--port", str(port),
        "--host", "127.0.0.1",
    ]
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(ROOT_DIR)
    )
    
    def _stream_logs():
        for line in proc.stdout:
            print(f"[server] {line.strip()}")
            
    threading.Thread(target=_stream_logs, daemon=True).start()
    
    url = f"http://127.0.0.1:{port}/"
    try:
        _wait_for_http_ready(url)
        yield url
    finally:
        proc.terminate()
        proc.wait()

def test_pvd_animation_state(paraview_server, shared_browser):
    page = shared_browser.new_page()
    try:
        page.on("console", lambda msg: print(f"[browser] {msg.text}"))
        page.goto(paraview_server)
        
        # Wait for UI to stabilize and ParaView to finish loading the file
        time.sleep(12.0) # Increased wait time
        
        # Read current time label from the toolbar: "<time> (<index>/<total>)"
        time_label = page.locator(
            "div.v-toolbar__content div.grey--text.text--darken-2"
        ).first

        # Time-dependent controls must appear for animation.pvd
        page.wait_for_selector(".mdi-play", timeout=20000)
        page.wait_for_selector(
            "div.v-toolbar__content div.grey--text.text--darken-2", timeout=20000
        )

        def get_time_info():
            text = time_label.inner_text().strip()
            match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*\((\d+)/(\d+)\)", text)
            assert match, f"Unexpected time label format: {text!r}"
            return {
                "current_time": float(match.group(1)),
                "time_index_displayed": int(match.group(2)),
                "total_timesteps": int(match.group(3)),
            }

        state = get_time_info()
        print(f"DEBUG Initial Time Label: {state}")

        # Initial state check from rendered UI
        assert state["total_timesteps"] == 4
        assert state["time_index_displayed"] == 1

        # Test Next Step button
        page.locator(".mdi-skip-next").first.click()
        time.sleep(1.5) 
        state = get_time_info()
        assert state["time_index_displayed"] == 2

        # Test Previous Step button
        page.locator(".mdi-skip-previous").first.click()
        time.sleep(1.5)
        state = get_time_info()
        assert state["time_index_displayed"] == 1

        # Test Play button
        page.locator(".mdi-play").first.click()
        page.wait_for_selector(".mdi-pause", timeout=5000)
        time.sleep(3.0)
        state = get_time_info()
        assert state["time_index_displayed"] > 1

        # Test Pause
        page.locator(".mdi-pause").first.click()
        page.wait_for_selector(".mdi-play", timeout=5000)
        time.sleep(1.5)
        state = get_time_info()
        final_index = state["time_index_displayed"]
        
        time.sleep(1.0)
        state = get_time_info()
        assert state["time_index_displayed"] == final_index
    except Exception as e:
        page.screenshot(path="failure_pvd_animation.png")
        raise e
    finally:
        page.close()
