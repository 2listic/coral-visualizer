
import pathlib
import subprocess
import sys
import time
import socket
import urllib.request
import os
import threading
import json
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
        
        # Function to get the current state from the window.trame.state
        def get_trame_state():
            return page.evaluate("""
                () => {
                    const s = window.trame.state;
                    if (!s) {
                        console.log("DEBUG: window.trame.state is null or undefined");
                        return null;
                    }
                    // Access properties directly from the state object
                    const stateObj = s.state || s; // Try both common structures
                    if (!stateObj) {
                        console.log("DEBUG: Actual state object not found.");
                        return null;
                    }
                    const res = {};
                    const keys = ['is_time_dependent', 'total_timesteps', 'time_index', 'current_time', 'time_playing'];
                    for (const key of keys) {
                        res[key] = stateObj[key];
                        console.log(`DEBUG State.${key}: ${res[key]}`);
                    }
                    console.log("DEBUG Final State Object: " + JSON.stringify(res));
                    return res;
                }
            """)

        # Wait until time-dependent state is confirmed
        page.wait_for_function("""
            () => {
                const s = window.trame && window.trame.state;
                if (!s) return false;
                const stateObj = s.state || s;
                if (!stateObj) return false;
                // Wait until is_time_dependent is explicitly true
                return stateObj.is_time_dependent === true;
            }
        """, timeout=20000) # Increased timeout for wait_for_function
        
        state = get_trame_state()
        print(f"DEBUG Initial State: {state}")
        
        # Initial state check
        assert state["is_time_dependent"] is True
        assert state["total_timesteps"] == 4
        assert state["time_index"] == 0

        # The time controls should appear for animation.pvd
        play_button_selector = 'div.v-toolbar__content button:has(i.mdi-play)'
        page.wait_for_selector(play_button_selector, timeout=20000)
        
        # Test Next Step button
        page.locator(".mdi-skip-next").first.click()
        time.sleep(1.5) 
        state = get_trame_state()
        assert state["time_index"] == 1

        # Test Previous Step button
        page.locator(".mdi-skip-previous").first.click()
        time.sleep(1.5)
        state = get_trame_state()
        assert state["time_index"] == 0

        # Test Play button
        page.locator(".mdi-play").first.click()
        time.sleep(3.0)
        state = get_trame_state()
        assert state["time_playing"] is True
        assert state["time_index"] > 0

        # Test Pause
        page.locator(".mdi-pause").first.click()
        time.sleep(1.5)
        state = get_trame_state()
        assert state["time_playing"] is False
        final_index = state["time_index"]
        
        time.sleep(1.0)
        state = get_trame_state()
        assert state["time_index"] == final_index
    except Exception as e:
        page.screenshot(path="failure_pvd_animation.png")
        raise e
    finally:
        page.close()
