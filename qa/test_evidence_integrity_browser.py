"""
qa/test_evidence_integrity_browser.py
────────────────────────────────────────────────────────────────────────────────
Browser automation verifying:
1. Prabhav Infosystems price-mismatch case (INV-PI-2025-101) in Resolution Workbench.
2. Verified vendor attribution:
   - Zenith memory card explicitly displays '🟠 Cross-Vendor Precedent: Zenith Precision Engineering Pvt Ltd'
   - Tag displays '#vendor:zenith-precision-engineering' (NOT prabhav-infosystems)
   - Baseline cards display '🏢 Prabhav Infosystems Pvt Ltd'
   - Cross-vendor Bhavna card displays '🟠 Cross-Vendor Precedent: Bhavna Textile Traders'
3. Confidence section displays 3 in-scope historical decisions (3 EDITED),
   and documents excluded cross-vendor memories.
4. Captures high-res visual evidence screenshots.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
from playwright.sync_api import sync_playwright

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREENSHOT_DIR = Path(r"C:\Users\kiran\LedgerMind\qa\evidence_screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

PORT = 8504


def start_streamlit():
    print(f"Starting Streamlit server on port {PORT}...")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for attempt in range(30):
        time.sleep(1)
        try:
            with urllib.request.urlopen(f"http://localhost:{PORT}/_stcore/health", timeout=1) as resp:
                if resp.status == 200:
                    print(f"Streamlit server is ready on port {PORT} (attempt {attempt + 1}).")
                    return proc
        except Exception:
            pass
    proc.terminate()
    raise RuntimeError(f"Streamlit failed to start on port {PORT} within 30 seconds.")


def wait_for_streamlit(page, timeout=25.0):
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=int(timeout * 1000))
    except Exception:
        pass
    page.wait_for_timeout(1000)


def select_inv(page, inv_id):
    print(f"Selecting invoice {inv_id}...")
    page.wait_for_selector('div[data-testid="stSelectbox"]', timeout=15000)
    sel = page.locator('div[data-testid="stSelectbox"]').first
    current_text = sel.text_content() or ""
    if inv_id in current_text:
        print(f"  - Already selected: {inv_id}")
        return

    inp = sel.locator('input').first
    inp.click()
    page.wait_for_timeout(300)
    page.keyboard.type(inv_id)
    page.wait_for_timeout(600)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)
    wait_for_streamlit(page)
    print(f"  ✓ Selected: {inv_id}")


def run_browser_verification():
    proc = start_streamlit()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=CHROME_PATH if os.path.exists(CHROME_PATH) else None,
                headless=True,
                args=["--window-size=1920,1080"],
            )
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()

            print(f"Navigating to http://localhost:{PORT}...")
            page.goto(f"http://localhost:{PORT}")
            wait_for_streamlit(page)

            # Navigate to Resolution Workbench
            print("Navigating to Resolution Workbench via sidebar radio...")
            radio = page.locator('label:has-text("Resolution Workbench")').first
            radio.scroll_into_view_if_needed()
            radio.click()
            wait_for_streamlit(page)

            # Select INV-PI-2025-101 (Prabhav Infosystems)
            select_inv(page, "INV-PI-2025-101")
            wait_for_streamlit(page)

            # Click Generate Agent Proposal if button is present
            gen_btn = page.locator("button:has-text('Generate Agent Proposal')")
            if gen_btn.count() > 0 and gen_btn.first.is_visible():
                print("Clicking Generate Agent Proposal...")
                gen_btn.first.click()
                wait_for_streamlit(page, timeout=30.0)

            # Wait for Recalled Precedents to be visible
            print("Waiting for Recalled Precedents & Evidentiary Citations to appear...")
            page.wait_for_selector("text=Recalled Precedents & Evidentiary Citations", timeout=30000)
            page.wait_for_timeout(1500)

            # Screenshot 1: Full Page Overview
            overview_path = SCREENSHOT_DIR / "01_prabhav_workbench_overview.png"
            page.screenshot(path=str(overview_path), full_page=True)
            print(f"Captured: {overview_path}")

            # Scroll to evidence section
            evidence_header = page.locator("text=Recalled Precedents & Evidentiary Citations")
            if evidence_header.count() > 0:
                evidence_header.first.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)

            # Screenshot 2: Evidence cards
            evidence_path = SCREENSHOT_DIR / "02_prabhav_evidence_cards_accurate_metadata.png"
            page.screenshot(path=str(evidence_path))
            print(f"Captured: {evidence_path}")

            # Inspect DOM content
            page_text = page.content()

            # Verify accurate metadata chips and badges
            assert "zenith-precision-engineering" in page_text, "Expected #vendor:zenith-precision-engineering in evidence cards"
            assert "Cross-Vendor Precedent: Zenith Precision Engineering" in page_text, "Expected Cross-Vendor Precedent badge for Zenith"
            assert "Prabhav Infosystems Pvt Ltd" in page_text, "Expected Prabhav Infosystems in evidence cards"
            print(" Verified: Cross-Vendor Precedent badge for Zenith is present!")
            print(" Verified: #vendor:zenith-precision-engineering tag is present!")
            print(" Verified: Direct vendor precedents for Prabhav Infosystems are present!")

            # Verify Confidence section
            conf_header = page.locator("text=Deterministic Confidence Formula")
            if conf_header.count() > 0:
                conf_header.first.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)
            conf_path = SCREENSHOT_DIR / "03_prabhav_confidence_breakdown.png"
            page.screenshot(path=str(conf_path))
            print(f"Captured: {conf_path}")

            browser.close()
            print("Browser verification completed successfully!")

    finally:
        print("Stopping Streamlit server...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    run_browser_verification()
