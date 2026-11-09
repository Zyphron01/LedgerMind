"""
qa/test_intake_fixes_browser.py
────────────────────────────────────────────────────────────────────────────────
Browser automation verifying:
1. Existing PO intake path (Nova Tech Supplies + PO-NOVA-001 + 18% GST + Billed 1100).
   Verifies NO UnboundLocalError for gst_map occurs!
2. Clean 3-way match invoice resolution in Workbench.
   Verifies:
   - Green 'THREE-WAY MATCH RECONCILED / CLEAN MATCH' banner is displayed (no red exception banner).
   - Agent Proposal generates cleanly without NameError for ConfidenceBand.
"""

import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.request
from playwright.sync_api import sync_playwright, Page

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREENSHOT_DIR = Path(r"C:\Users\kiran\LedgerMind\qa\intake_screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


PORT = 8503

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
                    print(f"  ✓ Streamlit server ready on http://localhost:{PORT} (attempt {attempt + 1})")
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


def run_fixes_verification():
    server_proc = start_streamlit()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME_PATH, headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.on("console", lambda msg: print(f"  [Chrome Console {msg.type}]: {msg.text}") if msg.type in ["error"] else None)
            page.on("pageerror", lambda exc: print(f"  [Chrome Page Error]: {exc}"))

            print(f"Opening http://localhost:{PORT}...")
            page.goto(f"http://localhost:{PORT}", wait_until="networkidle", timeout=45000)
            wait_for_ui(page)

            # -------------------------------------------------------------
            # TEST 1: INTAKE WITH EXISTING PURCHASE ORDER (NOVA TECH SUPPLIES)
            # -------------------------------------------------------------
            print("\n[Test 1] Navigating to New Invoice / Import page...")
            navigate(page, "New Invoice / Import")
            page.wait_for_selector('h1:has-text("New Invoice & Document Intake")', timeout=15000)

            print("  Selecting existing vendor and existing PO...")
            # Select vendor
            vend_sel = page.locator('div[data-testid="stSelectbox"]').first
            vend_sel.click()
            page.wait_for_timeout(400)
            page.keyboard.type("Nova Tech Supplies")
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            wait_for_ui(page)

            # Select existing PO: PO-NOVA-001
            po_sel = page.locator('div[data-testid="stSelectbox"]').nth(1)
            po_sel.click()
            page.wait_for_timeout(400)
            page.keyboard.type("PO-NOVA-001")
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            wait_for_ui(page)

            # Fill Invoice details
            inv_num_input = page.locator('input[aria-label*="Invoice Number"]').first
            inv_num_input.fill("INV-NOVA-2025-002")
            inv_num_input.press("Tab")
            page.wait_for_timeout(300)

            inv_price_input = page.locator('input[aria-label*="Billed Unit Price (INR)"]').first
            inv_price_input.fill("1100.00")  # Billed unit price 1100
            inv_price_input.press("Tab")
            page.wait_for_timeout(500)

            # Submit Intake
            try:
                save_btn = page.locator('button:has-text("Save All Documents & Run 3-Way Match")').first
                save_btn.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                save_btn.click()
                print("  Submitted. Waiting for save confirmation...")
            except Exception as e:
                page.screenshot(path=str(SCREENSHOT_DIR / "debug_intake_fixes.png"), full_page=True)
                print("  ❌ Submit failed! Saved debug screenshot.")
                print("  Alerts:", page.locator('div[data-testid="stAlert"]').all_text_contents())
                print("  Exceptions:", page.locator('div[data-testid="stException"]').all_text_contents())
                raise e

            # Verify NO UnboundLocalError occurred and success alert appears
            page.locator('div[data-testid="stAlert"]').filter(has_text="Successfully Saved").first.wait_for(timeout=20000)
            wait_for_ui(page)

            shot_existing_po = SCREENSHOT_DIR / "07_existing_po_intake_success.png"
            page.screenshot(path=str(shot_existing_po), full_page=True)
            print(f"  ✓ Existing PO intake succeeded without UnboundLocalError: {shot_existing_po.name}")

            # -------------------------------------------------------------
            # TEST 2: INTAKE CLEAN 3-WAY MATCH INVOICE
            # -------------------------------------------------------------
            print("\n[Test 2] Creating a Clean Three-Way Match Invoice...")
            # Select '+ Register New Vendor...'
            vend_sel = page.locator('div[data-testid="stSelectbox"]').first
            vend_sel.click()
            page.wait_for_timeout(400)
            page.keyboard.type("+ Register New Vendor")
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            wait_for_ui(page)

            v_name_input = page.locator('input[aria-label*="New Vendor Full Name"]').first
            v_name_input.fill("Apex Precision Tools Pvt Ltd")
            v_name_input.press("Tab")
            page.wait_for_timeout(300)

            v_gstin_input = page.locator('input[aria-label*="Vendor GSTIN"]').first
            v_gstin_input.fill("27AAACA9999M1Z1")
            v_gstin_input.press("Tab")
            page.wait_for_timeout(300)

            # Select '+ Create New Purchase Order' in PO dropdown
            po_sel = page.locator('div[data-testid="stSelectbox"]').nth(1)
            po_sel.click()
            page.wait_for_timeout(400)
            page.keyboard.type("+ Create New Purchase Order")
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            wait_for_ui(page)

            # PO details (Price 2000, Qty 10)
            po_num_input = page.locator('input[aria-label*="PO Number"]').first
            po_num_input.fill("PO-APEX-2025-001")
            po_num_input.press("Tab")
            page.wait_for_timeout(300)

            po_price_input = page.locator('input[aria-label*="Agreed Unit Price (INR)"]').first
            po_price_input.fill("2000.00")
            po_price_input.press("Tab")
            page.wait_for_timeout(300)

            # Invoice details matching exact PO price and qty
            inv_num_input = page.locator('input[aria-label*="Invoice Number"]').first
            inv_num_input.fill("INV-APEX-2025-101")
            inv_num_input.press("Tab")
            page.wait_for_timeout(300)

            inv_price_input = page.locator('input[aria-label*="Billed Unit Price (INR)"]').first
            inv_price_input.fill("2000.00")
            inv_price_input.press("Tab")
            page.wait_for_timeout(500)

            save_btn = page.locator('button:has-text("Save All Documents & Run 3-Way Match")').first
            save_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            save_btn.click()

            page.locator('div[data-testid="stAlert"]').filter(has_text="Successfully Saved").first.wait_for(timeout=20000)
            page.locator('div.lm-callout').filter(has_text="CLEAN THREE-WAY MATCH").first.wait_for(timeout=10000)
            wait_for_ui(page)

            shot_clean_intake = SCREENSHOT_DIR / "08_clean_match_intake_success.png"
            page.screenshot(path=str(shot_clean_intake), full_page=True)
            print(f"  ✓ Clean match intake saved with green match callout: {shot_clean_intake.name}")

            # -------------------------------------------------------------
            # TEST 3: RESOLUTION WORKBENCH FOR CLEAN MATCH
            # -------------------------------------------------------------
            print("\n[Test 3] Verifying Clean Match in Resolution Workbench...")
            navigate(page, "Resolution Workbench")
            page.wait_for_selector('h1:has-text("AP Exception Resolution Workbench")', timeout=15000)
            wait_for_ui(page)

            # Select clean invoice if not selected
            sel = page.locator('div[data-testid="stSelectbox"]').first
            sel_text = sel.text_content() or ""
            if "INV-APEX-2025-101" not in sel_text:
                sel.click()
                page.wait_for_timeout(400)
                page.keyboard.type("INV-APEX-2025-101")
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                wait_for_ui(page)

            # Verify green banner is present (NOT red EXCEPTION DETECTED)
            page.locator('div.lm-callout-success').filter(has_text="THREE-WAY MATCH RECONCILED").first.wait_for(timeout=10000)
            wb_text = page.locator('div[data-testid="stAppViewContainer"]').text_content() or ""
            assert "3-WAY MATCH EXCEPTION DETECTED" not in wb_text
            assert "THREE-WAY MATCH RECONCILED" in wb_text
            print("  ✓ Verified green 'THREE-WAY MATCH RECONCILED' banner displayed (no red exception banner).")

            # Click Generate Agent Proposal
            btn = page.locator('button:has-text("Generate Agent Proposal")').first
            btn.scroll_into_view_if_needed()
            btn.click()
            print("  Waiting for agent proposal...")
            page.get_by_text("Agent Resolution Proposal").first.wait_for(timeout=25000)
            wait_for_ui(page)

            proposal_text = page.locator('div[data-testid="stAppViewContainer"]').text_content() or ""
            assert "NameError" not in proposal_text
            assert "APPROVED" in proposal_text
            assert "ConfidenceBand" not in proposal_text
            print("  ✓ Proposal generated with APPROVED action and no ConfidenceBand NameError!")

            shot_clean_wb = SCREENSHOT_DIR / "09_clean_match_workbench_proposal.png"
            page.screenshot(path=str(shot_clean_wb), full_page=True)
            print(f"  ✓ Clean match workbench proposal captured: {shot_clean_wb.name}")

            browser.close()
            print("\n" + "=" * 70)
            print("ALL BROWSER VERIFICATION TESTS FOR INTAKE FIXES PASSED SUCCESSFULLY!")
            print("=" * 70)

    finally:
        print("Stopping Streamlit server...")
        server_proc.terminate()
        server_proc.wait()
        print("✓ Server stopped cleanly.")


if __name__ == "__main__":
    run_fixes_verification()

