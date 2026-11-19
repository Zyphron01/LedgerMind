# LEDGERMIND — VERIFIED CAPABILITIES & JUDGE-SAFE CLAIMS MATRIX

**Document:** Authoritative Capability Verification Audit  
**Target:** Hackathon Judges, Evaluators, and Presentation Team  
**Standard:** Every claim must be grounded in verified code paths, passing tests, or database inspection.  

---

## 1. PROVEN CAPABILITIES (Demonstrated Live / Automated Tests)

These features have been independently verified through running code, passing automated tests, live container queries, or direct SQLite inspection.

| Capability | Implementation Evidence | Test / Runtime Verification | Status |
|---|---|---|---|
| **Deterministic 3-Way Matching** | `agent/matcher.py:match_invoice()` | `tests/test_matcher.py` (all tests pass) | **PROVEN** |
| **Price Variance Detection** | `agent/matcher.py:32-150` | Verified on `INV-HWB-DEMO-001` (₹1,180 variance / +10.0%) | **PROVEN** |
| **Quantity Shortfall Detection** | `agent/matcher.py:75-95` | Verified on `INV-DL-2025-101` (50 units shortfall / ₹94,400 delta) | **PROVEN** |
| **Duplicate Invoice Detection** | `agent/matcher.py:50-70` | Verified on `INV-KS-2025-101` (100% duplicate match flagged) | **PROVEN** |
| **Statutory GST Rate Integrity** | `agent/matcher.py:110-140` | Verified on `INV-NPD-2025-101` (12% vs 18% statutory mismatch) | **PROVEN** |
| **SQLite Relational Persistence** | `data/store.py`, `data/ledgermind.db` | Read-only SQL query confirmed 27 invoices, 26 POs, 22 GRNs, 2 reviews | **PROVEN** |
| **Temporal Policy Retrieval** | `policy/retriever.py:23-63` | `tests/test_policy_rag.py:37-74` (Version scoping by date verified) | **PROVEN** |
| **Policy-Precedent Conflict Engine** | `policy/conflict.py:25-282` | `tests/test_policy_rag.py:108-210` (Scenarios A, B, C verified) | **PROVEN** |
| **Deterministic Policy Supremacy** | `agent/resolver.py:625-654` | `tests/test_policy_rag.py:211-257` (Code-level override enforced) | **PROVEN** |
| **Live Hindsight Recall** | `memory/client.py`, `memory/operations.py` | Live query against `http://localhost:8888` returned 9 records | **PROVEN** |
| **Memory Deduplication** | `agent/resolver.py:82-198` | 9 raw memory records grouped to 1 verified decision with 8 facts | **PROVEN** |
| **Offline Memory Failover** | `memory/offline_store.py:15-80` | `tests/test_async_hindsight_lifecycle.py:110-120` | **PROVEN** |
| **Deterministic Groq Fallback** | `agent/resolver.py:218-350` | `tests/test_agent_resolver.py:15-60` (Synthesizes fallback if offline) | **PROVEN** |
| **Heuristic Confidence Meter** | `agent/confidence.py:65-150` | `tests/test_memory_intelligence_retrieval.py:340-372` | **PROVEN** |
| **Human Review Retention** | `agent/feedback.py:25-85` | `data/store.py` contains verified human reviews with status `SYNCED` | **PROVEN** |
| **Reflect Cache Bank Isolation** | `memory/reflect_cache.py:90-150` | `tests/test_memory_intelligence_retrieval.py:400-430` | **PROVEN** |
| **Budget Telemetry Separation** | `memory/budget_guard.py:135-215` | `tests/test_memory_intelligence_retrieval.py:440-470` | **PROVEN** |
| **Full Regression Suite** | Entire codebase | `python -m pytest tests/ -q` (**130 passed in 8.25s**) | **PROVEN** |

---

## 2. QUALIFIED CAPABILITIES (Grounded in Code, but Subject to Specific Conditions)

These features exist and function, but must be described with precise technical qualifications to avoid misleading judges.

| Claim / Capability | Verified Reality | Required Presentation Qualification |
|---|---|---|
| **"Policy RAG"** | Structured Pydantic policy models retrieved by enum and temporal date windows (`policy/retriever.py`). | **MUST QUALIFY:** This is *structured, version-scoped policy retrieval*, not embedding-based vector search over unstructured PDFs. |
| **"100% Policy Compliance"** | Evaluated on 20 held-out synthetic invoices in `eval/held_out_evaluation_report.json`. | **MUST QUALIFY:** Benchmark was executed using an isolated, reproducible test harness with `DeterministicSimulatedLLM` to model baseline vs precedent behaviors. |
| **"₹4.08 Lakhs Flagged"** | Sum of duplicate invoices, quantity shortfalls, and unapproved price variances across 20 held-out cases. | **MUST QUALIFY:** This is *potential overpayment exposure flagged before disbursement*, not actual historical cash leakage recovered. |
| **"Groq LLM Intelligence"** | Groq API client configured for `openai/gpt-oss-120b` in `agent/llm.py`. | **MUST QUALIFY:** Production app uses live Groq when online, but falls back to deterministic rule logic if rate-limited or offline. |
| **"Institutional Learning"** | Human review submissions are retained into `ledgermind-live-demo` via Hindsight API. | **MUST QUALIFY:** Learning occurs via dynamic vector memory retrieval and reflection caching, not by fine-tuning neural network weights. |

---

## 3. NOT IMPLEMENTED (STRICTLY DO NOT CLAIM)

These capabilities are either future roadmap items or architectural non-goals. **Under no circumstances should the team claim these are currently functional.**

| Feature / Claim | Status | Why It Must Not Be Claimed |
|---|---|---|
| **Autonomous Payment Execution** | **NOT IMPLEMENTED** | LedgerMind is an advisory tool with human-in-the-loop review. It does not execute bank transfers or connect to SWIFT/UPI. |
| **Live SAP / Oracle ERP Integration** | **NOT IMPLEMENTED** | Ingestion occurs via CSV/JSON or direct UI forms; direct SAP RFC/BAPI connectors are on the future enterprise roadmap. |
| **Supabase Cloud Synchronization** | **NOT IMPLEMENTED** | The active data layer is local SQLite (`data/ledgermind.db`). No cloud Supabase database is connected. |
| **Cloud Hosting / Web Deployment** | **NOT IMPLEMENTED** | The application runs locally on `localhost:8501`. It is not deployed to AWS, Vercel, or Streamlit Community Cloud. |
| **PDF Document OCR Extraction** | **NOT IMPLEMENTED** | The application processes structured invoice data; it does not parse scanned receipt photos or run OCR models like Tesseract. |
| **Automatic Bank Account Debiting** | **NOT IMPLEMENTED** | Non-goal; financial disbursements require certified human treasury authorization. |
| **"Guaranteed 100% Fraud Elimination"** | **NOT IMPLEMENTED** | Exaggerated marketing claim. LedgerMind flags duplicate submissions and control discrepancies, but cannot detect off-book collusion. |
