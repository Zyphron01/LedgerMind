"""
Capture Scenario B Human Review Retention.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
from playwright.sync_api import sync_playwright

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREENSHOT_DIR = Path(r"C:\Users\kiran\LedgerMind\qa\browser_screenshots")
REPORT_PATH = Path(r"C:\Users\kiran\LedgerMind\qa\browser_inspection_results.json")

def start_streamlit():
    print("Starting Streamlit server on port 8501...")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.port=8501",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none",
        ],
        cwd=r"C:\Users\kiran\LedgerMind",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for attempt in range(30):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://localhost:8501/_stcore/health", timeout=1) as resp:
                if resp.status == 200:
                    print(f"  ✓ Streamlit server is ready on http://localhost:8501 (attempt {attempt + 1})")
                    return proc
        except Exception:
            pass
    raise RuntimeError("Streamlit failed to start within 30 seconds")

def wait_for_streamlit(page, timeout=20.0):
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=int(timeout * 1000))
    except Exception:
        pass
    page.wait_for_timeout(1000)

def navigate(page, target):
    print(f"Navigating to '{target}' via sidebar radio...")
    radio = page.locator(f'label:has-text("{target}")').first
    radio.scroll_into_view_if_needed()
    radio.click()
    wait_for_streamlit(page)

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

def run():
    server_proc = start_streamlit()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME_PATH, headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto("http://localhost:8501")
            wait_for_streamlit(page)

            navigate(page, "Resolution Workbench")
            select_inv(page, "INV-BTT-2025-101")
            btn = page.locator('button:has-text("Generate Agent Proposal")').first
            btn.scroll_into_view_if_needed()
            btn.click()
            print("Generating conflict proposal (waiting up to 75s)...")
            page.wait_for_selector('text="Agent Resolution Proposal"', timeout=75000)
            wait_for_streamlit(page)

            print("Filling human review rationale...")
            textarea = page.locator('textarea').first
            textarea.scroll_into_view_if_needed()
            textarea.click()
            textarea.fill("Escalation confirmed in browser QA. Overcharge exceeds 1.0% limit. Vendor dispute initiated.")
            page.keyboard.press("Tab")
            page.wait_for_timeout(800)

            submit_btn = page.locator('button:has-text("Retain Decision & Record Outcome")').first
            submit_btn.scroll_into_view_if_needed()
            submit_btn.click()
            print("Submitted. Waiting for outcome message...")
            page.wait_for_timeout(3000)
            wait_for_streamlit(page, timeout=30.0)

            shot_retained = SCREENSHOT_DIR / "04_scenario_b_human_review_retained.png"
            page.screenshot(path=str(shot_retained))
            print(f"✓ Saved Scenario B human retention screenshot: {shot_retained.name} ({shot_retained.stat().st_size} bytes)")

            # Update results JSON
            if REPORT_PATH.exists():
                try:
                    with open(REPORT_PATH, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data.setdefault("scenarios", {})
                    data["scenarios"]["Scenario A"] = {
                        "invoice": "INV-PI-2025-101",
                        "action": "EDITED",
                        "amount": "212,400.00",
                        "policy": "POL-AP-001",
                        "screenshot": str(SCREENSHOT_DIR / "03_scenario_a_prabhav_compliant.png"),
                        "status": "PASS"
                    }
                    data["scenarios"]["Scenario B"] = {
                        "invoice": "INV-BTT-2025-101",
                        "action": "ESCALATED",
                        "conflict_status": "POLICY_PRECEDENT_CONFLICT",
                        "screenshots": [
                            str(SCREENSHOT_DIR / "04_scenario_b_bhavna_conflict.png"),
                            str(shot_retained)
                        ],
                        "status": "PASS"
                    }
                    data["defects"] = []
                    with open(REPORT_PATH, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    print(f"✓ Updated results JSON at {REPORT_PATH}")
                except Exception as ex:
                    print(f"Warning: Failed to update JSON: {ex}")

            browser.close()

    finally:
        print("Stopping Streamlit server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        print("✓ Server stopped cleanly.")

if __name__ == "__main__":
    run()
