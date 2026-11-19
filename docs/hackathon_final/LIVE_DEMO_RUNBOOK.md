# LEDGERMIND — LIVE DEMO RUNBOOK & OPERATIONAL GUIDE

**Target:** Live Hackathon Stage / Judge Evaluation  
**Estimated Demo Time:** 3–4 Minutes  
**Prerequisites:** Python 3.11–3.14 on Windows, Docker Desktop running Hindsight  

---

## 1. Pre-Flight Verification & Service Startup

### A. Verify Local Hindsight Container
Ensure the Hindsight Docker container is running before launching the application:
```powershell
# Check Hindsight container health
curl.exe http://localhost:8888/health
# Expected: {"status":"healthy","database":"connected",...}
```
*If unreachable:* Ensure Docker Desktop is started. Run `docker ps` to verify the container named `hindsight` is active on port `8888`.

### B. Launch Streamlit Application
Open a clean PowerShell terminal in `C:\Users\kiran\LedgerMind`:
```powershell
# Start LedgerMind Streamlit application
streamlit run app.py
```
- Local URL: `http://localhost:8501`
- Network URL: Displayed in terminal.

---

## 2. Live Demo Script & Step-by-Step Navigation

### Step 1: System Overview & Sidebar Verification (30 Seconds)
1. **Navigate to:** `http://localhost:8501` (Loads **Overview** page by default).
2. **Point out the Sidebar:**
   - Hindsight Service Status: `🟢 ONLINE (Local Container: http://localhost:8888)`
   - LLM Inference Status: `🟢 ONLINE (Groq openai/gpt-oss-120b)`
   - Active Bank indicator: `ledgermind-live-demo`
3. **Overview Metrics:** Show total invoices (27), total POs (26), total GRNs (22), and gross discrepancy summary.
4. **Key Talking Point:** *"LedgerMind is running locally on our machine with live connections to our SQLite database and Hindsight memory container."*

---

### Step 2: Real Invoice & 3-Way Match Deep Inspection (1 Minute)
1. **Navigate to:** **Invoice Queue** page via top/sidebar navigation.
2. **Action:** Scroll to the **Three-Way Match Deep Inspector**.
3. **Select Invoice:** `INV-HWB-DEMO-001` (Supplier: *Apex Precision Tools Pvt Ltd*).
4. **Point out the Match Cards:**
   - **Billed Unit Price:** ₹1,100.00
   - **Agreed PO Unit Price:** ₹1,000.00
   - **Gross Discrepancy:** ₹1,180.00 (+10.0% variance including 18% GST).
   - **Exception Banner:** Red alert displaying `PRICE_MISMATCH`.
5. **Click:** Blue button **"Resolve in Workbench"** (seamlessly transitions with state preserved).

---

### Step 3: Resolution Workbench & Policy-Supremacy Guard (1.5 Minutes)
1. **Arrive at:** **Resolution Workbench** (Selected invoice is already loaded: `INV-HWB-DEMO-001`).
2. **Configuration:**
   - Agent Memory Mode: `Memory ON (Precedent-Grounded)`
   - Active Target Memory Bank: `🟡 ledgermind-live-demo`
3. **Click:** Primary button **"🤖 Generate Agent Proposal"**.
4. **Observe the Results:**
   - **Section 1 (Agent Proposal):** Proposed Action: `REJECTED`. Proposed Payable: `₹12,980.00 -> Rejected`.
   - **Section 2 (Policy Intelligence Card):**
     - Governing Policy: `POL-AP-001 (v2.0)` — *Invoice Price Variance Tolerance & Underpayment Credit Standard*.
     - Authoritative Directive quoted: *"Contracted price tolerance is strictly 0.0%... Price overages exceeding 5.0% must be REJECTED."*
     - Status: `COMPLIANT_PRECEDENT` (or Policy-governed mandate).
5. **Now Demonstrate Policy Supremacy Conflict (Scenario B):**
   - Switch invoice dropdown to: **`INV-BTT-2025-101`** (*Bhavna Textile Traders*).
   - Click **"🤖 Generate Agent Proposal"**.
   - **Show the Conflict:**
     - The Policy Intelligence card turns **Red/Amber**: `⚠️ POLICY–PRECEDENT CONFLICT DETECTED`.
     - Read the finding aloud: *"Written policy POL-AP-001 v2.0 caps unamended price tolerance at 1.00%... Past informal approvals violate written financial controls. Overriding recommendation to ESCALATED."*
     - Designated Authority: `Procurement Category Lead / Finance Controller`.
6. **Key Talking Point:** *"Notice what just happened. The historical human reviewer approved this 2% overcharge. A naive AI would have copied that mistake. LedgerMind detected that the human violated written policy and deterministically forced an escalation."*

---

### Step 4: Memory Intelligence & Verified Deduplication (45 Seconds)
1. **Navigate to:** **Memory Intelligence** page.
2. **Bank Selection:** Select `ledgermind-live-demo`.
3. **Vendor Selection:** Select `Zenith Precision Engineering Pvt Ltd`.
4. **Point out the Metrics:**
   - Raw Memory Records: **9**
   - Unique Source Decisions: **1**
   - Historical Decision Pattern: `REJECTED: 1`
   - Provenance Badge: `🟢 LIVE HINDSIGHT ENGINE (Active Container)`
5. **Expand Details:** Click on the record to show the source citation (`feedback-INV-ZENITH-2025-101`) and the 8 grouped supporting facts.
6. **Key Talking Point:** *"A raw vector search returns 9 fragmented observations. LedgerMind groups them into 1 verified historical decision, preventing artificial confidence inflation."*

---

## 3. Safe Read-Only Verification Commands (Terminal Proof)

If technical judges ask to verify database records or container health directly in the terminal, run these safe read-only commands:

```powershell
# 1. Verify live SQLite record for demo invoice
python -c "import sqlite3; c=sqlite3.connect('data/ledgermind.db'); print(c.execute('SELECT invoice_number, vendor_name, unit_price_inr, total_inr FROM invoices WHERE invoice_number=\'INV-HWB-DEMO-001\'').fetchone())"

# 2. Verify human review audit trail
python -c "import sqlite3; c=sqlite3.connect('data/ledgermind.db'); print(c.execute('SELECT invoice_number, decision, hindsight_status FROM human_reviews').fetchall())"

# 3. Verify Hindsight health
curl.exe -s http://localhost:8888/health | Select-String "healthy"
```

---

## 4. Fallback Routes & Graceful Degradation

### A. What if Groq API is Rate-Limited or Offline?
- **What happens:** The application catches the exception automatically and engages `_generate_deterministic_fallback()`.
- **What you will see:** An amber `FALLBACK` pill appears next to the proposed action.
- **Judge Narrative:** *"Groq cloud experienced a rate limit, but notice that LedgerMind did not crash. Our deterministic fallback engine applied our exact 3-way match math and policy rules to generate the resolution proposal."*

### B. What if Hindsight Container Stops Unexpectedly?
- **What happens:** `MemoryClient` times out and engages `offline_memory.jsonl`.
- **What you will see:** Provenance badge updates to `💾 OFFLINE AUDIT STORE`. All historical records remain fully readable with honest data lineage badges.
- **Judge Narrative:** *"Our memory adapter provides resilient offline failover. If the vector service drops, our local immutable JSONL store ensures the AP queue never halts."*

---

## 5. What to AVOID During the Live Demo

- **DO NOT** click `"🔄 Reseed All Data"` or run database migrations during the demo.
- **DO NOT** delete or recreate Docker containers while Streamlit is open.
- **DO NOT** submit dozens of random human reviews into the baseline bank (the UI protects `ledgermind-ap-exceptions`, but keep reviews clean in `ledgermind-live-demo`).
- **DO NOT** repeatedly click `"🔄 Generate / Refresh Profile"` in rapid succession to avoid triggering local LLM synthesis loops.

---

## 6. Fast Recovery Steps (Non-Destructive)

If Streamlit becomes unresponsive or a browser tab freezes:
1. Press `Ctrl + C` in the PowerShell terminal to stop Streamlit.
2. Re-run: `streamlit run app.py`.
3. Open a fresh browser tab at `http://localhost:8501`.
4. *Data integrity note:* SQLite records and Hindsight memory are persisted to disk and are completely unaffected by Streamlit restarts.
