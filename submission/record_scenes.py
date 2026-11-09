"""
submission/record_scenes.py
────────────────────────────────────────────────────────────────────────────────
Automates realistic, smooth Playwright 1920x1080 screen recordings of the real
LedgerMind application directly into submission/video/source_recordings/
"""

import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
from playwright.sync_api import sync_playwright

PORT = 8508
BASE_URL = f"http://localhost:{PORT}"
RECORDINGS_DIR = Path(r"C:\Users\kiran\LedgerMind\submission\video\source_recordings")
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def start_streamlit_server():
    print(f"Starting LedgerMind Streamlit server on port {PORT}...")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["HINDSIGHT_MODE"] = "local"
    env["HINDSIGHT_LOCAL_URL"] = "http://localhost:8888"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            f"--server.port={PORT}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none",
        ],
        cwd=r"C:\Users\kiran\LedgerMind",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for attempt in range(30):
        time.sleep(1)
        if proc.poll() is not None:
            out, _ = proc.communicate()
            raise RuntimeError(f"Streamlit terminated prematurely ({proc.returncode}):\n{out}")
        try:
            with urllib.request.urlopen(f"{BASE_URL}/_stcore/health", timeout=1) as resp:
                if resp.status == 200:
                    print(f"Streamlit ready on port {PORT} (attempt {attempt + 1})")
                    return proc
        except Exception:
            pass
    proc.terminate()
    raise RuntimeError(f"Failed to start Streamlit on port {PORT} within 30s")


def wait_st(page, timeout=15.0):
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=int(timeout * 1000))
    except Exception:
        pass
    page.wait_for_timeout(800)


def safe_hover(page, selector, timeout=1500):
    try:
        loc = page.locator(selector)
        if loc.count() > 0:
            loc.first.hover(timeout=timeout)
    except Exception:
        pass


def smooth_scroll(page, target_y, steps=25, delay=40):
    current_y = page.evaluate("window.scrollY")
    diff = target_y - current_y
    for i in range(1, steps + 1):
        y = current_y + diff * (i / steps)
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(delay)


def record_scene1_overview(p):
    print("Recording Scene 1: Problem & System Overview (~39s)...")
    clip_dir = RECORDINGS_DIR / "temp_scene1"
    clip_dir.mkdir(parents=True, exist_ok=True)

    browser = p.chromium.launch(
        executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
        headless=True,
        args=["--window-size=1920,1080"],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(clip_dir),
        record_video_size={"width": 1920, "height": 1080},
    )
    page = context.new_page()

    page.goto(BASE_URL)
    wait_st(page)
    page.wait_for_timeout(3000)

    # Hover over system health badges safely
    safe_hover(page, "text=Hindsight Memory Engine")
    page.wait_for_timeout(2500)
    safe_hover(page, "text=SQLite")
    page.wait_for_timeout(2500)

    # Smooth scroll down to exception types matrix
    smooth_scroll(page, 450, steps=30, delay=50)
    page.wait_for_timeout(4000)

    # Safe hover on discrepancy cards
    safe_hover(page, "text=Price Mismatch")
    page.wait_for_timeout(3500)
    safe_hover(page, "text=Quantity Discrepancy")
    page.wait_for_timeout(3500)

    # Scroll further to show historical distribution
    smooth_scroll(page, 900, steps=30, delay=50)
    page.wait_for_timeout(5000)

    # Scroll back to top
    smooth_scroll(page, 0, steps=30, delay=40)
    page.wait_for_timeout(6000)

    context.close()
    browser.close()

    # Rename recorded file
    webm_files = list(clip_dir.glob("*.webm"))
    if webm_files:
        dest = RECORDINGS_DIR / "clip_scene1.webm"
        if dest.exists():
            dest.unlink()
        webm_files[0].rename(dest)
        print(f"  ✓ Saved {dest}")


def record_scene3a_intake(p):
    print("Recording Scene 3A: Intake & Invoice Queue (~46s)...")
    clip_dir = RECORDINGS_DIR / "temp_scene3a"
    clip_dir.mkdir(parents=True, exist_ok=True)

    browser = p.chromium.launch(
        executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
        headless=True,
        args=["--window-size=1920,1080"],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(clip_dir),
        record_video_size={"width": 1920, "height": 1080},
    )
    page = context.new_page()

    page.goto(BASE_URL)
    wait_st(page)

    # Navigate to New Invoice / Import
    radio = page.locator('label:has-text("New Invoice / Import")').first
    radio.click()
    wait_st(page)
    page.wait_for_timeout(2500)

    # Scroll to intake form
    smooth_scroll(page, 300, steps=20, delay=40)
    page.wait_for_timeout(2000)

    # Fill invoice fields if inputs available
    inv_num_input = page.locator('input[aria-label="Invoice Number"]')
    if inv_num_input.count() > 0:
        inv_num_input.first.click()
        page.wait_for_timeout(500)

    smooth_scroll(page, 600, steps=25, delay=40)
    page.wait_for_timeout(3500)

    # Show live discrepancy calculation callout
    smooth_scroll(page, 950, steps=25, delay=40)
    page.wait_for_timeout(5000)

    # Navigate to Invoice Queue
    q_radio = page.locator('label:has-text("Invoice Queue")').first
    q_radio.click()
    wait_st(page)
    page.wait_for_timeout(3000)

    # Scroll through queue showing the invoices
    smooth_scroll(page, 500, steps=30, delay=50)
    page.wait_for_timeout(4000)

    smooth_scroll(page, 1000, steps=30, delay=50)
    page.wait_for_timeout(5000)

    context.close()
    browser.close()

    webm_files = list(clip_dir.glob("*.webm"))
    if webm_files:
        dest = RECORDINGS_DIR / "clip_scene3a.webm"
        if dest.exists():
            dest.unlink()
        webm_files[0].rename(dest)
        print(f"  ✓ Saved {dest}")


def record_scene3b_workbench(p):
    print("Recording Scene 3B: Resolution Workbench & Human Review (~37s)...")
    clip_dir = RECORDINGS_DIR / "temp_scene3b"
    clip_dir.mkdir(parents=True, exist_ok=True)

    browser = p.chromium.launch(
        executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
        headless=True,
        args=["--window-size=1920,1080"],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(clip_dir),
        record_video_size={"width": 1920, "height": 1080},
    )
    page = context.new_page()

    page.goto(BASE_URL)
    wait_st(page)

    # Navigate to Resolution Workbench
    radio = page.locator('label:has-text("Resolution Workbench")').first
    radio.click()
    wait_st(page)

    # Select INV-PI-2025-101
    sel = page.locator('div[data-testid="stSelectbox"]').first
    inp = sel.locator('input').first
    inp.click()
    page.wait_for_timeout(300)
    page.keyboard.type("INV-PI-2025-101")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    wait_st(page)

    # Click Generate Agent Proposal if available
    gen_btn = page.locator("button:has-text('Generate Agent Proposal')")
    if gen_btn.count() > 0 and gen_btn.first.is_visible():
        gen_btn.first.click()
        wait_st(page, timeout=25.0)

    page.wait_for_timeout(2000)

    # Scroll to proposal card (EDITED, amount, confidence)
    smooth_scroll(page, 450, steps=25, delay=40)
    page.wait_for_timeout(4000)

    # Scroll to governing policy clause POL-AP-002
    smooth_scroll(page, 850, steps=25, delay=40)
    page.wait_for_timeout(4500)

    # Scroll down to Human Reviewer Panel
    smooth_scroll(page, 1600, steps=30, delay=50)
    page.wait_for_timeout(5000)

    # Hover on submit button / final decision
    safe_hover(page, "button:has-text('Submit Human Decision')")
    page.wait_for_timeout(5000)

    context.close()
    browser.close()

    webm_files = list(clip_dir.glob("*.webm"))
    if webm_files:
        dest = RECORDINGS_DIR / "clip_scene3b.webm"
        if dest.exists():
            dest.unlink()
        webm_files[0].rename(dest)
        print(f"  ✓ Saved {dest}")


def record_scene4_hindsight(p):
    print("Recording Scene 4: Hindsight Vector Memory & Comparison (~50s)...")
    clip_dir = RECORDINGS_DIR / "temp_scene4"
    clip_dir.mkdir(parents=True, exist_ok=True)

    browser = p.chromium.launch(
        executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
        headless=True,
        args=["--window-size=1920,1080"],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(clip_dir),
        record_video_size={"width": 1920, "height": 1080},
    )
    page = context.new_page()

    page.goto(BASE_URL)
    wait_st(page)

    # Go to Resolution Workbench
    radio = page.locator('label:has-text("Resolution Workbench")').first
    radio.click()
    wait_st(page)

    # Scroll directly to Recalled Precedents & Evidentiary Citations
    smooth_scroll(page, 1050, steps=30, delay=40)
    page.wait_for_timeout(3500)

    # Highlight Hindsight Vector DB storage badge
    safe_hover(page, "text=Hindsight Vector DB")
    page.wait_for_timeout(3500)

    # Expand the Zenith supporting facts details block!
    try:
        details_summary = page.locator("summary:has-text('additional extracted facts')")
        if details_summary.count() > 0:
            details_summary.first.click(timeout=2000)
    except Exception:
        pass
        page.wait_for_timeout(3500)

    # Scroll to Prabhav baseline precedent cards
    smooth_scroll(page, 1400, steps=25, delay=40)
    page.wait_for_timeout(4000)

    # Scroll down to confidence score breakdown
    smooth_scroll(page, 1850, steps=25, delay=40)
    page.wait_for_timeout(4000)

    # Now navigate to Memory OFF vs ON Comparison page!
    comp_radio = page.locator('label:has-text("Memory OFF vs ON Comparison")').first
    if comp_radio.count() > 0:
        comp_radio.scroll_into_view_if_needed()
        comp_radio.click()
    wait_st(page)
    page.wait_for_timeout(3000)

    # Smooth scroll through comparison view
    smooth_scroll(page, 450, steps=25, delay=40)
    page.wait_for_timeout(4500)

    smooth_scroll(page, 900, steps=25, delay=40)
    page.wait_for_timeout(5000)

    context.close()
    browser.close()

    webm_files = list(clip_dir.glob("*.webm"))
    if webm_files:
        dest = RECORDINGS_DIR / "clip_scene4.webm"
        if dest.exists():
            dest.unlink()
        webm_files[0].rename(dest)
        print(f"  ✓ Saved {dest}")


def record_scene5_intelligence(p):
    print("Recording Scene 5: Memory Intelligence & Behavioral Audit (~26s)...")
    clip_dir = RECORDINGS_DIR / "temp_scene5"
    clip_dir.mkdir(parents=True, exist_ok=True)

    browser = p.chromium.launch(
        executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
        headless=True,
        args=["--window-size=1920,1080"],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(clip_dir),
        record_video_size={"width": 1920, "height": 1080},
    )
    page = context.new_page()

    page.goto(BASE_URL)
    wait_st(page)

    # Navigate to Memory Intelligence
    intel_radio = page.locator('label:has-text("Memory Intelligence")').first
    if intel_radio.count() > 0:
        intel_radio.scroll_into_view_if_needed()
        intel_radio.click()
    wait_st(page)
    page.wait_for_timeout(3000)

    # Scroll through vendor dossier and decision breakdown
    smooth_scroll(page, 400, steps=25, delay=40)
    page.wait_for_timeout(4000)

    # Scroll to reflect behavioral synthesis & token budget telemetry
    smooth_scroll(page, 850, steps=25, delay=40)
    page.wait_for_timeout(5000)

    smooth_scroll(page, 1300, steps=25, delay=40)
    page.wait_for_timeout(4000)

    context.close()
    browser.close()

    webm_files = list(clip_dir.glob("*.webm"))
    if webm_files:
        dest = RECORDINGS_DIR / "clip_scene5.webm"
        if dest.exists():
            dest.unlink()
        webm_files[0].rename(dest)
        print(f"  ✓ Saved {dest}")


def main():
    server_proc = start_streamlit_server()
    try:
        with sync_playwright() as p:
            if not (RECORDINGS_DIR / "clip_scene1.webm").exists():
                record_scene1_overview(p)
            if not (RECORDINGS_DIR / "clip_scene3a.webm").exists():
                record_scene3a_intake(p)
            if not (RECORDINGS_DIR / "clip_scene3b.webm").exists():
                record_scene3b_workbench(p)
            if not (RECORDINGS_DIR / "clip_scene4.webm").exists():
                record_scene4_hindsight(p)
            if not (RECORDINGS_DIR / "clip_scene5.webm").exists():
                record_scene5_intelligence(p)
        print("All screen recording clips captured successfully!")
    finally:
        print("Stopping Streamlit server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except Exception:
            server_proc.kill()


if __name__ == "__main__":
    main()
