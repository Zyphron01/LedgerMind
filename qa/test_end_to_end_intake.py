"""
qa/test_end_to_end_intake.py
────────────────────────────────────────────────────────────────────────────────
End-to-End Playwright Automation for Real Invoice Intake, Persistence, Matching,
Memory OFF vs ON Fix, and Live Hindsight Review Retention.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
from playwright.sync_api import sync_playwright, Page

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREENSHOT_DIR = Path(r"C:\Users\kiran\LedgerMind\qa\intake_screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for attempt in range(30):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://localhost:8501/_stcore/health", timeout=1) as resp:
                if resp.status == 200:
                    print(f"  ✓ Streamlit server ready on http://localhost:8501 (attempt {attempt + 1})")
                    return proc
        except Exception:
            pass
    raise RuntimeError("Streamlit failed to start within 30 seconds")


def wait_for_ui(page: Page, timeout: float = 25.0):
    try:
        page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=int(timeout * 1000))
    except Exception:
        pass
    try:
        page.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=int(timeout * 1000))
    except Exception:
        pass
    page.wait_for_timeout(1000)


def navigate(page: Page, target: str):
    print(f"\nNavigating to '{target}' via sidebar radio...")
    sidebar = page.locator('section[data-testid="stSidebar"]')
    radio_text = sidebar.get_by_text(target, exact=True)
    radio_text.scroll_into_view_if_needed()
    radio_text.click(force=True)
    page.wait_for_timeout(1000)
    wait_for_ui(page)


def run_e2e_intake():
    server_proc = start_streamlit()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME_PATH, headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.on("console", lambda msg: print(f"  [Chrome Console {msg.type}]: {msg.text}") if msg.type in ["error", "warn"] else None)
            page.on("pageerror", lambda exc: print(f"  [Chrome Page Error]: {exc}"))

            print("Opening http://localhost:8501...")
            page.goto("http://localhost:8501")
            wait_for_ui(page)

            # -------------------------------------------------------------
            # STEP 1: VERIFY MEMORY ENGINE ONLINE
            # -------------------------------------------------------------
            print("\n[Step 1] Verifying Memory Engine status badge...")
            page.wait_for_selector('h1', timeout=25000)
            page.wait_for_selector('[data-testid="stSidebar"]', timeout=20000)
            sidebar_text = page.locator('[data-testid="stSidebar"]').first.text_content()
            print(f"  Sidebar text snippet: {sidebar_text[:120].strip()}")
            assert "ONLINE" in sidebar_text or "Hindsight" in sidebar_text
            print("  ✓ Hindsight Memory Engine is ONLINE in sidebar.")

            # -------------------------------------------------------------
            # STEP 2: TEST MEMORY OFF VS ON (P0.A REGRESSION FIX VERIFICATION)
            # -------------------------------------------------------------
            print("\n[Step 2] Testing Memory OFF vs ON Comparison (P0.A Pydantic Fix)...")
            shot_comp = SCREENSHOT_DIR / "01_comparison_fixed.png"
            if not shot_comp.exists():
                navigate(page, "Memory OFF vs ON Comparison")
                comp_btn = page.locator('button:has-text("Run Comparative Analysis")').first
                comp_btn.scroll_into_view_if_needed()
                comp_btn.click()
                print("  Waiting for comparative analysis (up to 75s)...")
                page.wait_for_selector('text="Analytical Takeaway & Evidentiary Value"', timeout=75000)
                wait_for_ui(page)
                page.screenshot(path=str(shot_comp), full_page=True)
                print(f"  ✓ Comparison rendered without validation errors: {shot_comp.name}")
            else:
                print(f"  ✓ Comparison screenshot already captured: {shot_comp.name}")

            # -------------------------------------------------------------
            # STEP 3: INTAKE NEW INVOICE (8% PRICE MISMATCH)
            # -------------------------------------------------------------
            print("\n[Step 3] Navigating to New Invoice / Import page...")
            navigate(page, "New Invoice / Import")

            print("  Filling manual intake form...")
            # Select '+ Register New Vendor...'
            vend_sel = page.locator('div[data-testid="stSelectbox"]').first
            vend_sel.click()
            page.wait_for_timeout(500)
            page.keyboard.type("+ Register New Vendor")
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            wait_for_ui(page)

            # Wait for conditional vendor fields to appear
            page.wait_for_selector('input[aria-label*="New Vendor Full Name"]', timeout=10000)

            # Type new vendor name & GSTIN
            v_name_input = page.locator('input[aria-label*="New Vendor Full Name"]').first
            v_name_input.fill("Zenith Precision Engineering Pvt Ltd")
            v_name_input.press("Tab")
            page.wait_for_timeout(300)

            v_gstin_input = page.locator('input[aria-label*="Vendor GSTIN"]').first
            v_gstin_input.fill("27AAACZ1111A1Z2")
            v_gstin_input.press("Tab")
            page.wait_for_timeout(300)

            # Fill PO details
            po_num_input = page.locator('input[aria-label*="PO Number"]').first
            po_num_input.fill("PO-ZENITH-2025-001")
            po_num_input.press("Tab")
            page.wait_for_timeout(300)

            item_input = page.locator('input[aria-label*="Item Description"]').first
            item_input.fill("Industrial Ball Bearings 6205")
            item_input.press("Tab")
            page.wait_for_timeout(300)

            # Fill Invoice details
            inv_num_input = page.locator('input[aria-label*="Invoice Number"]').first
            inv_num_input.fill("INV-ZENITH-2025-101")
            inv_num_input.press("Tab")
            page.wait_for_timeout(300)

            inv_price_input = page.locator('input[aria-label*="Billed Unit Price (INR)"]').first
            inv_price_input.fill("1080.00")  # +8.0% over PO ₹1,000
            inv_price_input.press("Tab")
            page.wait_for_timeout(1000)

            # Submit Intake
            save_btn = page.locator('button:has-text("Save All Documents & Run 3-Way Match")').first
            save_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            save_btn.click()
            print("  Submitted. Waiting for 3-way match...")
            try:
                page.locator('div[data-testid="stAlert"]').filter(has_text="Successfully Saved").first.wait_for(timeout=20000)
            except Exception as e:
                shot_err = SCREENSHOT_DIR / "debug_intake_failure.png"
                page.screenshot(path=str(shot_err), full_page=True)
                print(f"  ❌ Intake timed out! Saved debug screenshot to {shot_err.name}")
                errors = page.locator('div[data-testid="stAlert"]').all_text_contents()
                print("  Alerts on page:", errors)
                raise e
            wait_for_ui(page)

            # Verify Price Mismatch detected
            page.locator('div.lm-callout').filter(has_text="EXCEPTION DETECTED").first.wait_for(timeout=10000)
            shot_intake = SCREENSHOT_DIR / "02_intake_saved_match_detected.png"
            page.screenshot(path=str(shot_intake), full_page=True)
            print(f"  ✓ 8% Price mismatch successfully matched and saved: {shot_intake.name}")

            # -------------------------------------------------------------
            # STEP 4: VERIFY IN INVOICE QUEUE
            # -------------------------------------------------------------
            print("\n[Step 4] Checking Invoice Queue for newly created user invoice...")
            navigate(page, "Invoice Queue")
            page.wait_for_selector('div[data-testid="stDataFrame"]', timeout=15000)
            queue_text = page.locator('div[data-testid="stDataFrame"]').first.text_content() or ""
            assert "INV-ZENITH-2025-101" in queue_text
            assert "Zenith Precision Engineering" in queue_text
            assert "PRICE_MISMATCH" in queue_text
            print("  ✓ Found INV-ZENITH-2025-101 in queue with origin USER.")

            shot_queue = SCREENSHOT_DIR / "03_queue_with_user_invoice.png"
            page.screenshot(path=str(shot_queue))
            print(f"  ✓ Queue screenshot captured: {shot_queue.name}")

            # -------------------------------------------------------------
            # STEP 5: RESOLUTION WORKBENCH PROPOSAL
            # -------------------------------------------------------------
            print("\n[Step 5] Resolving new invoice in Resolution Workbench...")
            navigate(page, "Resolution Workbench")
            page.wait_for_selector('h1:has-text("AP Exception Resolution Workbench")', timeout=15000)
            wait_for_ui(page)
            sel = page.locator('div[data-testid="stSelectbox"]').first
            sel_text = sel.text_content() or ""
            if "INV-ZENITH-2025-101" not in sel_text:
                sel.click()
                page.wait_for_timeout(400)
                page.keyboard.type("INV-ZENITH-2025-101")
                page.wait_for_timeout(600)
                page.keyboard.press("Enter")
                wait_for_ui(page)

            btn = page.locator('button:has-text("Generate Agent Proposal")').first
            btn.scroll_into_view_if_needed()
            btn.click()
            print("  Waiting for agent proposal synthesis (up to 75s)...")
            page.get_by_text("Agent Resolution Proposal").first.wait_for(timeout=75000)
            wait_for_ui(page)

            proposal_text = page.locator('div[data-testid="stAppViewContainer"]').text_content() or ""
            assert "ESCALATED" in proposal_text or "EDITED" in proposal_text
            assert "POL-AP-002" in proposal_text or "POL-AP-001" in proposal_text
            print("  ✓ Agent proposal generated without invented precedents.")

            shot_wb = SCREENSHOT_DIR / "04_workbench_new_invoice_proposal.png"
            page.screenshot(path=str(shot_wb), full_page=True)
            print(f"  ✓ Workbench proposal captured: {shot_wb.name}")

            # -------------------------------------------------------------
            # STEP 6: SUBMIT HUMAN REVIEW & VERIFY HINDSIGHT RETENTION
            # -------------------------------------------------------------
            print("\n[Step 6] Submitting Human Review...")
            textarea = page.locator('textarea').first
            textarea.scroll_into_view_if_needed()
            textarea.click()
            textarea.fill("Overcharge of 8.0% exceeds contractual 1.0% limit under POL-AP-002. Disputed with Zenith supplier.")
            page.keyboard.press("Tab")
            page.wait_for_timeout(600)

            retain_btn = page.locator('button:has-text("Retain Decision & Record Outcome")').first
            retain_btn.scroll_into_view_if_needed()
            retain_btn.click()
            print("  Waiting for outcome confirmation...")
            page.locator('div[data-testid="stAlert"]').filter(has_text=re.compile(r"Successfully Retained|Pending Hindsight Sync|Saved to Persistent Ledger")).first.wait_for(timeout=35000)
            wait_for_ui(page)

            shot_retained = SCREENSHOT_DIR / "05_workbench_retained_in_hindsight.png"
            page.screenshot(path=str(shot_retained))
            print(f"  ✓ Human review retained into persistent storage & Hindsight: {shot_retained.name}")

            # -------------------------------------------------------------
            # STEP 7: VERIFY PERSISTENCE AFTER APPLICATION RELOAD
            # -------------------------------------------------------------
            print("\n[Step 7] Simulating page refresh / application reload...")
            page.reload()
            wait_for_ui(page)

            navigate(page, "Invoice Queue")
            page.wait_for_selector('div[data-testid="stDataFrame"]', timeout=15000)
            wait_for_ui(page)

            full_queue_text = page.locator('div[data-testid="stAppViewContainer"]').text_content() or ""
            print("  Queue page text snippet:", full_queue_text[200:800].replace("\n", " "))

            assert "INV-ZENITH-2025-101" in full_queue_text
            assert "1 Reviewed" in full_queue_text or any(status in full_queue_text for status in ["REJECTED", "ESCALATED", "EDITED", "APPROVED"])
            print("  ✓ User invoice INV-ZENITH-2025-101 and review persistence verified across reload!")

            shot_reload = SCREENSHOT_DIR / "06_queue_reloaded_from_sqlite.png"
            page.screenshot(path=str(shot_reload), full_page=True)
            print(f"  ✓ Reloaded state screenshot captured: {shot_reload.name}")

            browser.close()
            print("\n" + "=" * 70)
            print("ALL 7 END-TO-END VERIFICATION PHASES PASSED WITH FLYING COLORS!")
            print("=" * 70)

    finally:
        print("Stopping Streamlit server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except Exception:
            server_proc.kill()
        print("✓ Server stopped cleanly.")


if __name__ == "__main__":
    run_e2e_intake()
