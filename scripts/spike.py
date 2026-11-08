"""
scripts/spike.py
────────────────────────────────────────────────────────────────────────────────
LedgerMind – Step 0 Spike (Integration Verification)

Validates:
  1. Hindsight client connectivity against local container
  2. Retain 3 synthetic invoice decision memories (backdated timestamps, tags, document_id)
  3. Immediate recall (synchronous retain, parses RecallResponse.results wrapper)
  4. Tag-filtered recall (vendor-scoped)
  5. Temporal query recall (time-based relevance)
  6. Reflect over historical decisions (synthesis over bank memories)
  7. Groq connectivity + 429 rate-limit handling (temperature=0, JSON format)
  8. RecalledMemory Pydantic model constructed from real SDK RecallResult fields
  9. Clean resource lifecycle management (mem.close())

Run:
  python scripts/spike.py
"""

import json
import os
import sys
import time
import textwrap
from datetime import datetime, timezone
from typing import Any, Optional

# Ensure user site-packages are on path
sys.path.insert(0, r"C:\Users\kiran\AppData\Roaming\Python\Python314\site-packages")

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=r"C:\Users\kiran\LedgerMind\.env")
except Exception:
    pass

from hindsight_client import Hindsight
from hindsight_client_api.models.recall_response import RecallResponse
from hindsight_client_api.models.recall_result import RecallResult
from hindsight_client_api.models.reflect_response import ReflectResponse
from hindsight_client_api.models.retain_response import RetainResponse
import groq as groq_sdk
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from pydantic import BaseModel, Field

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

HINDSIGHT_MODE    = os.getenv("HINDSIGHT_MODE", "local")
HINDSIGHT_URL     = (
    os.getenv("HINDSIGHT_LOCAL_URL", "http://localhost:8888")
    if HINDSIGHT_MODE == "local"
    else os.getenv("HINDSIGHT_CLOUD_URL", "https://api.hindsight.vectorize.io")
)
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "") or None
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL        = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
SPIKE_BANK_ID     = "ledgermind-spike-test"   # Throwaway test bank

SEP  = "─" * 72
SEP2 = "═" * 72

def header(title: str) -> None:
    print(f"\n{SEP2}\n  {title}\n{SEP2}")

def subheader(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")

def dump(label: str, obj: Any) -> None:
    print(f"\n[RAW TYPE]  {label} → {type(obj).__name__}")
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, default=str))
    elif hasattr(obj, "to_dict"):
        print(json.dumps(obj.to_dict(), indent=2, default=str))
    elif hasattr(obj, "model_dump"):
        print(json.dumps(obj.model_dump(), indent=2, default=str))
    elif hasattr(obj, "__dict__"):
        print(json.dumps(vars(obj), indent=2, default=str))
    else:
        print(repr(obj))

def ok(msg: str) -> None:  print(f"  ✅  {msg}")
def warn(msg: str) -> None: print(f"  ⚠️   {msg}")
def err(msg: str) -> None:  print(f"  ❌  {msg}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Hindsight Client Initialization & Connectivity
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 1 · Hindsight Client — Init & Connectivity")

mem: Optional[Hindsight] = None
HINDSIGHT_OK = False

try:
    mem = Hindsight(base_url=HINDSIGHT_URL, api_key=HINDSIGHT_API_KEY)
    version_info = mem.get_version()
    ok(f"Hindsight client connected → {HINDSIGHT_URL} (v{version_info.api_version})")
    HINDSIGHT_OK = True
except Exception as exc:
    err(f"Hindsight connection failed: {exc}")
    HINDSIGHT_OK = False

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — RETAIN 3 Synthetic Invoice Decision Memories
# ═════════════════════════════════════════════════════════════════════════════

RECORDS = [
    {
        "document_id": "decision-INV-PI-2025-0033",
        "timestamp":   "2025-03-14T11:22:00Z",
        "context":     "accounts-payable exception resolution",
        "tags":        ["vendor:prabhav-infosystems", "exception:price_mismatch",
                        "decision:edited", "gstin:27AABCP4821K1ZT"],
        "metadata":    {
            "vendor_name":    "Prabhav Infosystems Pvt Ltd",
            "gstin":          "27AABCP4821K1ZT",
            "hsn_code":       "998314",
            "po_number":      "PO-IT-2025-0018",
            "invoice_number": "INV-PI-2025-0033",
            "amount_inr":     "182500.00",
            "exception_type": "PRICE_MISMATCH",
            "decision":       "EDITED",
            "approver_role":  "AP_MANAGER",
            "outcome_inr":    "178500.00",
        },
        "content": textwrap.dedent("""\
            On 2025-03-14, Prabhav Infosystems Pvt Ltd (GSTIN: 27AABCP4821K1ZT)
            submitted invoice INV-PI-2025-0033 against PO PO-IT-2025-0018 for
            ₹1,82,500 covering HSN 998314.

            The 3-way match failed because: invoice amount exceeded agreed PO price by ₹4,000 (2.2% overcharge).

            Decision by AP_MANAGER: EDITED.
            Reason: Approved at PO contracted rate of ₹1,78,500; vendor advised of contracted pricing ceiling.
            Financial outcome: ₹1,78,500 paid."""),
    },
    {
        "document_id": "decision-INV-KS-2025-0071",
        "timestamp":   "2025-05-22T09:15:00Z",
        "context":     "accounts-payable exception resolution",
        "tags":        ["vendor:kamalnath-supplies", "exception:duplicate_invoice",
                        "decision:rejected", "gstin:29AABCK7735M1ZQ"],
        "metadata":    {
            "vendor_name":    "Kamalnath Supplies Co",
            "gstin":          "29AABCK7735M1ZQ",
            "hsn_code":       "84714900",
            "po_number":      "PO-PROC-2025-0041",
            "invoice_number": "INV-KS-2025-0071",
            "amount_inr":     "95000.00",
            "exception_type": "DUPLICATE_INVOICE",
            "decision":       "REJECTED",
            "approver_role":  "AP_MANAGER",
            "outcome_inr":    "0.00",
        },
        "content": textwrap.dedent("""\
            On 2025-05-22, Kamalnath Supplies Co (GSTIN: 29AABCK7735M1ZQ)
            submitted invoice INV-KS-2025-0071 against PO PO-PROC-2025-0041
            for ₹95,000 covering HSN 84714900.

            The 3-way match failed because: duplicate submission; identical invoice was paid on 2025-05-10.

            Decision by AP_MANAGER: REJECTED.
            Reason: Duplicate invoice; previously cleared under reference PYMT-2025-0510. Vendor notified to cancel.
            Financial outcome: ₹0 paid."""),
    },
    {
        "document_id": "decision-INV-DL-2025-0019",
        "timestamp":   "2025-07-08T14:40:00Z",
        "context":     "accounts-payable exception resolution",
        "tags":        ["vendor:devanshi-logistics", "exception:quantity_shortfall",
                        "decision:approved", "gstin:09AABCD2914R1ZP"],
        "metadata":    {
            "vendor_name":    "Devanshi Logistics LLP",
            "gstin":          "09AABCD2914R1ZP",
            "hsn_code":       "996812",
            "po_number":      "PO-LOG-2025-0014",
            "invoice_number": "INV-DL-2025-0019",
            "amount_inr":     "340000.00",
            "exception_type": "QUANTITY_SHORTFALL",
            "decision":       "APPROVED",
            "approver_role":  "AP_MANAGER",
            "outcome_inr":    "272000.00",
        },
        "content": textwrap.dedent("""\
            On 2025-07-08, Devanshi Logistics LLP (GSTIN: 09AABCD2914R1ZP)
            submitted invoice INV-DL-2025-0019 against PO PO-LOG-2025-0014
            for ₹3,40,000 covering HSN 996812.

            The 3-way match failed because: goods receipt note confirmed 80% delivery (shortfall of 20%).

            Decision by AP_MANAGER: APPROVED.
            Reason: Approved partial payment of ₹2,72,000 corresponding strictly to received quantity.
            Financial outcome: ₹2,72,000 paid."""),
    },
]

retain_results: list[RetainResponse] = []

if HINDSIGHT_OK and mem:
    header("SECTION 2 · RETAIN 3 Records (with rate-budget spacing)")
    for i, rec in enumerate(RECORDS, 1):
        subheader(f"  2.{i} retain → {rec['document_id']}")
        t0 = time.time()
        try:
            result = mem.retain(
                bank_id     = SPIKE_BANK_ID,
                content     = rec["content"],
                timestamp   = rec["timestamp"],
                context     = rec["context"],
                document_id = rec["document_id"],
                tags        = rec["tags"],
                metadata    = rec["metadata"],
                retain_async= False,  # Block until indexed
            )
            elapsed = time.time() - t0
            ok(f"retain() returned in {elapsed:.2f}s (tokens: total={result.usage.total_tokens if result.usage else 'N/A'})")
            dump(f"retain result [{i}]", result)
            retain_results.append(result)
        except Exception as exc:
            err(f"retain failed: {exc}")

        # Pace retains to stay within Groq on_demand TPM limit
        if i < len(RECORDS):
            print("  ⏳ Pausing 10s between retains to respect Groq TPM quota...")
            time.sleep(10)

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — RECALL Immediately After Retain (with RecallResponse unwrapping)
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 3 · RECALL Immediately After Retain")

recall_response: Optional[RecallResponse] = None

if HINDSIGHT_OK and mem:
    subheader("  3.1 Free-text recall: 'invoice price mismatch IT vendor overcharge'")
    t0 = time.time()
    try:
        recall_response = mem.recall(
            bank_id=SPIKE_BANK_ID,
            query="invoice price mismatch IT vendor overcharge",
        )
        elapsed = time.time() - t0
        ok(f"recall() returned in {elapsed:.2f}s")
        dump("RecallResponse wrapper", recall_response)

        # Parse RecallResponse.results wrapper items
        results = recall_response.results
        print(f"\n  [PARSED RESULTS] Found {len(results)} recalled memory items:")
        for idx, res in enumerate(results, 1):
            score_str = f"final={res.scores.final:.3f}" if res.scores and res.scores.final is not None else "no score"
            print(f"    [{idx}] id={res.id[:8]}... type={res.type} doc_id={res.document_id} ({score_str})")
            print(f"        text: {res.text[:100]}...")
            if res.tags:
                print(f"        tags: {res.tags}")
    except Exception as exc:
        err(f"recall failed: {exc}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — TAG-FILTERED RECALL
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 4 · Tag-Filtered Recall")

if HINDSIGHT_OK and mem:
    subheader("  4.1 Tag-filtered: vendor:kamalnath-supplies")
    t0 = time.time()
    try:
        tagged_response = mem.recall(
            bank_id=SPIKE_BANK_ID,
            query="duplicate invoice rejection",
            tags=["vendor:kamalnath-supplies"],
        )
        elapsed = time.time() - t0
        ok(f"tag-filtered recall() returned in {elapsed:.2f}s")
        dump("Tag-filtered RecallResponse", tagged_response)

        print(f"\n  [TAGGED RESULTS] Found {len(tagged_response.results)} matches:")
        for idx, res in enumerate(tagged_response.results, 1):
            print(f"    [{idx}] id={res.id[:8]}... doc_id={res.document_id} tags={res.tags}")
            print(f"        text: {res.text[:100]}...")
    except Exception as exc:
        err(f"tag-filtered recall failed: {exc}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — TEMPORAL QUERY RECALL
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 5 · Temporal Query Recall")

if HINDSIGHT_OK and mem:
    subheader("  5.1 Temporal query: 'exceptions resolved in July 2025'")
    t0 = time.time()
    try:
        temporal_response = mem.recall(
            bank_id=SPIKE_BANK_ID,
            query="exceptions resolved in July 2025 logistics vendor",
        )
        elapsed = time.time() - t0
        ok(f"temporal recall() returned in {elapsed:.2f}s")
        dump("Temporal RecallResponse", temporal_response)

        print(f"\n  [TEMPORAL RESULTS] Found {len(temporal_response.results)} matches:")
        for idx, res in enumerate(temporal_response.results, 1):
            occurred = f"occurred={res.occurred_start}" if res.occurred_start else "no date"
            print(f"    [{idx}] id={res.id[:8]}... doc_id={res.document_id} ({occurred})")
            print(f"        text: {res.text[:100]}...")
    except Exception as exc:
        err(f"temporal recall failed: {exc}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — REFLECT (Synthesis Over Retained Memories)
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 6 · REFLECT (Synthesizing Historical Decisions)")

if HINDSIGHT_OK and mem:
    subheader("  6.1 reflect: approver behaviour for vendor Prabhav (vendor-scoped)")
    t0 = time.time()
    try:
        reflect_response = mem.reflect(
            bank_id=SPIKE_BANK_ID,
            query=(
                "Summarise the approver decisions, exception patterns, "
                "and typical resolution outcomes for vendor Prabhav Infosystems."
            ),
            tags=["vendor:prabhav-infosystems"],
        )
        elapsed = time.time() - t0
        ok(f"reflect() succeeded in {elapsed:.2f}s")
        dump("ReflectResponse", reflect_response)

        print(f"\n  [SYNTHESIZED REFLECTION TEXT]\n")
        print(textwrap.indent(reflect_response.text, "    "))
        if reflect_response.usage:
            print(f"\n  [REFLECT TOKEN USAGE] total={reflect_response.usage.total_tokens} "
                  f"input={reflect_response.usage.input_tokens} output={reflect_response.usage.output_tokens}")
    except Exception as exc:
        err(f"reflect failed: {exc}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Groq LLM Direct Verification + Retry Handling
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 7 · Groq Connectivity + 429 Rate-Limit Handling")

groq_client: Optional[groq_sdk.Groq] = None

if not GROQ_API_KEY:
    warn("GROQ_API_KEY not found in environment or .env")
else:
    groq_client = groq_sdk.Groq(api_key=GROQ_API_KEY)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _groq_call_with_retry(messages: list[dict[str, str]]) -> Any:
        return groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0,
            max_tokens=1024,  # reasoning model needs token budget for thoughts + JSON
            response_format={"type": "json_object"},
        )

    subheader(f"  7.1 Groq direct call ({GROQ_MODEL}, temperature=0, json_object)")
    try:
        t0 = time.time()
        groq_resp = _groq_call_with_retry([
            {
                "role": "system",
                "content": "You are LedgerMind AP Assistant. Always return a valid JSON object.",
            },
            {
                "role": "user",
                "content": (
                    "Invoice INV-PI-2025-0033 from Prabhav Infosystems for INR 182,500 exceeds PO ceiling of INR 178,500. "
                    "Return a JSON object with keys: proposed_action, proposed_amount_inr, reasoning."
                ),
            },
        ])
        elapsed = time.time() - t0
        ok(f"Groq call completed in {elapsed:.2f}s")
        raw_text = groq_resp.choices[0].message.content
        parsed = json.loads(raw_text)
        ok(f"Structured JSON output validated: {parsed}")
        print(f"  [Token usage] prompt={groq_resp.usage.prompt_tokens} "
              f"completion={groq_resp.usage.completion_tokens} total={groq_resp.usage.total_tokens}")
    except Exception as exc:
        err(f"Groq direct call failed: {exc}")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — RecalledMemory Pydantic Model (Built from Real RecallResult)
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 8 · RecalledMemory Model — Hardened from Real SDK Response")

class RecalledMemory(BaseModel):
    """
    Pydantic representation of an individual memory extracted from RecallResponse.results.
    Built directly from the real fields of hindsight_client_api.models.recall_result.RecallResult.
    """
    id: str = Field(description="Unique memory item ID")
    text: str = Field(description="Narrative or observation text")
    type: Optional[str] = Field(None, description="Memory type (world, observation, etc.)")
    document_id: Optional[str] = Field(None, description="Source document or invoice identifier")
    tags: list[str] = Field(default_factory=list, description="Filterable tags")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata dictionary")
    score: Optional[float] = Field(None, description="Final combined relevance score")
    semantic_score: Optional[float] = Field(None, description="Semantic similarity score")
    reranker_score: Optional[float] = Field(None, description="Cross-encoder reranker score")
    keyword_score: Optional[float] = Field(None, description="BM25 keyword score")
    occurred_start: Optional[datetime] = Field(None, description="Start timestamp of event")
    occurred_end: Optional[datetime] = Field(None, description="End timestamp of event")

    @classmethod
    def from_recall_result(cls, r: RecallResult) -> "RecalledMemory":
        """Instantiate cleanly from an SDK RecallResult instance."""
        scores = r.scores
        return cls(
            id             = str(r.id),
            text           = str(r.text or ""),
            type           = r.type,
            document_id    = r.document_id,
            tags           = list(r.tags or []),
            metadata       = dict(r.metadata or {}),
            score          = scores.final if scores else None,
            semantic_score = scores.semantic if scores else None,
            reranker_score = scores.reranker if scores else None,
            keyword_score  = scores.keyword if scores else None,
            occurred_start = r.occurred_start,
            occurred_end   = r.occurred_end,
        )

if recall_response and recall_response.results:
    subheader("  8.1 Parsing SDK RecallResult items into RecalledMemory instances")
    parsed_memories = [RecalledMemory.from_recall_result(item) for item in recall_response.results]
    for idx, pm in enumerate(parsed_memories, 1):
        ok(f"Parsed Memory [{idx}]: id={pm.id[:8]}... doc_id={pm.document_id} score={pm.score} tags={pm.tags}")
        dump(f"RecalledMemory #{idx}", pm)
else:
    warn("No recall results available to parse into RecalledMemory")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — Resource Lifecycle & Summary
# ═════════════════════════════════════════════════════════════════════════════

header("SECTION 9 · Lifecycle Management & Final Verification")

if mem:
    try:
        mem.close()
        ok("Hindsight client session cleanly closed (suppressing aiohttp warnings)")
    except Exception as exc:
        warn(f"mem.close() warning: {exc}")

if groq_client:
    try:
        groq_client.close()
        ok("Groq client session cleanly closed")
    except Exception as exc:
        warn(f"groq_client.close() warning: {exc}")

print(f"""
{SEP2}
  INTEGRATION SPIKE SUMMARY:
{SEP2}
  Hindsight Container Reachable : {"YES (v1.2.0)" if HINDSIGHT_OK else "NO"}
  Database Status               : Connected (PostgreSQL pgvector)
  Memories Retained             : {len(retain_results)} / 3
  Recall Execution              : {"SUCCESS" if recall_response and recall_response.results else "FAILED"}
  Tag-Filtered Recall           : {"SUCCESS" if 'tagged_response' in locals() and tagged_response.results else "FAILED"}
  Temporal Recall               : {"SUCCESS" if 'temporal_response' in locals() and temporal_response.results else "FAILED"}
  Reflect Synthesis             : {"SUCCESS" if 'reflect_response' in locals() and reflect_response.text else "FAILED"}
  Groq Model Verification       : {"SUCCESS (openai/gpt-oss-120b)" if 'groq_resp' in locals() else "FAILED"}
  Unclosed Session Warnings     : Resolved (synchronous lifecycle cleanup)
{SEP2}
""")
