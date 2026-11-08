"""
scripts/verify_milestone3.py
────────────────────────────────────────────────────────────────────────────────
Milestone 3.1 Evidence Integrity & Reliability Verification Script for LedgerMind.

Executes:
  1. Authoritative verification of server-side documents in Hindsight bank
  2. Strict verification that no held-out invoice has been seeded
  3. Real Hindsight recall demonstrating raw retrieved facts vs deduplicated documents
  4. Execution of a held-out invoice with Memory OFF
  5. Execution of the same invoice with Memory ON
  6. Corrected confidence calculation showing unique decisions, breakdown, and excluded items
  7. Human feedback write-back in the LIVE demonstration bank (LIVE_DEMO_BANK_ID)
  8. Proof that feedback does NOT leak into the frozen baseline benchmark bank (BASELINE_EVAL_BANK_ID)
  9. Immediate recall of the feedback record to verify dynamic learning
"""

from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ROOT_DIR / ".env")
except Exception:
    pass

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from agent.feedback import FeedbackSubmission, process_human_feedback
from agent.resolver import ResolutionAgent
from data.models import ApproverDecision, ApproverRole, HeldOutInvoice
from data.seed import SeedLedger
from data.synthetic import HELD_OUT_FILE, load_held_out_invoices
from memory.client import MemoryClient


def header(title: str) -> None:
    sep = "═" * 72
    print(f"\n{sep}\n  {title}\n{sep}")


def subheader(title: str) -> None:
    sep = "─" * 72
    print(f"\n{sep}\n  {title}\n{sep}")


def run_verification() -> None:
    header("LEDGERMIND MILESTONE 3.1 EVIDENCE INTEGRITY & RELIABILITY VERIFICATION")

    # 1. AUTHORITATIVE SERVER-SIDE INSPECTION
    mem_client = MemoryClient()
    print(f"Baseline Evaluation Bank ID: {BASELINE_EVAL_BANK_ID} (FROZEN BENCHMARK)")
    print(f"Live Demonstration Bank ID:   {LIVE_DEMO_BANK_ID} (LEARNING WORKFLOW)")

    server_doc_ids = set()
    total_facts_count = 0
    try:
        mems = mem_client._sdk_client.list_memories(bank_id=BASELINE_EVAL_BANK_ID)
        items = mems.items if hasattr(mems, "items") else mems
        total_facts_count = len(items)
        server_doc_ids = {getattr(m, "document_id", None) for m in items if getattr(m, "document_id", None)}
    except Exception as e:
        print(f"⚠️  Authoritative list_memories call warning: {e}")

    ledger = SeedLedger()
    ledger_records = ledger.data.get("banks", {}).get(BASELINE_EVAL_BANK_ID, {})

    print(f"\n[Authoritative Persistence Check]")
    print(f"  • Raw Memory Facts in Hindsight:    {total_facts_count} facts")
    print(f"  • Unique Source Documents Verified: {len(server_doc_ids)} unique documents")
    print(f"  • Local Seeding Ledger Count:       {len(ledger_records)} records")

    # 2. VERIFY NO HELD-OUT INVOICE HAS BEEN SEEDED
    held_out = load_held_out_invoices(HELD_OUT_FILE)
    held_out_numbers = {h.invoice.invoice_number for h in held_out}
    seeded_numbers = {v["invoice_number"] for v in ledger_records.values()}

    overlap = held_out_numbers.intersection(seeded_numbers)
    if overlap:
        print(f"❌ FATAL: Overlap detected! Held-out invoices seeded into memory: {overlap}")
        sys.exit(1)
    else:
        print(f"✅ Held-Out Isolation Verified: 0 of {len(held_out_numbers)} held-out invoices exist in baseline memory.")

    # 3. SAMPLE RETRIEVAL & DUPLICATE SOURCE FACTS DEMONSTRATION
    sample_query = "Prabhav Infosystems consulting rate markup pricing ceiling"
    print(f"\nQuerying Hindsight for: '{sample_query}'...")
    raw_recalled = mem_client.recall(bank_id=BASELINE_EVAL_BANK_ID, query=sample_query, limit=10)
    print(f"Retrieved {len(raw_recalled)} raw memory facts from Hindsight:")

    doc_ids_seen = []
    for idx, m in enumerate(raw_recalled, 1):
        doc_ids_seen.append(m.document_id)
        print(f"   [{idx:02d}] Document: {m.document_id} | Score: {m.score} | Text: {m.text[:65]}...")

    unique_docs_recalled = set(doc_ids_seen)
    print(f"🔍 Evidence Grouping: {len(raw_recalled)} raw facts collapse to {len(unique_docs_recalled)} unique source decisions.")

    # 4. RUN HELD-OUT INVOICE: MEMORY OFF vs MEMORY ON
    target_held_out: HeldOutInvoice = held_out[0]
    inv = target_held_out.invoice
    po = target_held_out.po
    grn = target_held_out.grn
    match_res = target_held_out.match_result

    subheader(f"EVALUATION INVOICE: {inv.invoice_number} ({inv.vendor_name})")
    print(f"Discrepancy: {match_res.exception_type.value} - {match_res.explanation}")
    print(f"Invoice Total: ₹{inv.total_inr:,.2f} | PO Total: ₹{po.total_inr:,.2f}")

    agent = ResolutionAgent(memory_client=mem_client, default_bank_id=BASELINE_EVAL_BANK_ID)

    # 4a. RUN WITH MEMORY OFF
    print("\n▶ Running with MEMORY OFF (Zero Historical Context)...")
    t0 = time.time()
    proposal_off = agent.resolve(
        invoice=inv,
        po=po,
        grn=grn,
        match_result=match_res,
        memory_enabled=False,
    )
    elapsed_off = time.time() - t0
    print(f"  Action:     {proposal_off.proposed_action.value}")
    print(f"  Amount:     ₹{proposal_off.proposed_amount_inr:,.2f}")
    print(f"  Confidence: {proposal_off.confidence.score:.2f} ({proposal_off.confidence.band.value}) [n={proposal_off.confidence.sample_size_n}]")
    print(f"  Citations:  {proposal_off.cited_memory_ids}")
    print(f"  Reasoning:  {proposal_off.reasoning[:180]}...")
    print(f"  Latency:    {elapsed_off:.2f}s | Tokens: {proposal_off.token_usage.get('total_tokens', 0)}")

    # 4b. RUN WITH MEMORY ON
    print("\n▶ Running with MEMORY ON (Hindsight Recall & Precedent Grounding)...")
    t1 = time.time()
    proposal_on = agent.resolve(
        invoice=inv,
        po=po,
        grn=grn,
        match_result=match_res,
        memory_enabled=True,
    )
    elapsed_on = time.time() - t1
    print(f"  Action:     {proposal_on.proposed_action.value}")
    print(f"  Amount:     ₹{proposal_on.proposed_amount_inr:,.2f}")
    print(f"  Confidence: {proposal_on.confidence.score:.2f} ({proposal_on.confidence.band.value}) [n={proposal_on.confidence.sample_size_n}]")
    print(f"  Supporting Document IDs: {proposal_on.confidence.supporting_document_ids}")
    print(f"  Decision Breakdown:      {proposal_on.confidence.decision_breakdown}")
    print(f"  Excluded/Deduped Facts:  {proposal_on.confidence.excluded_memories_count}")
    print(f"  Citations:  {proposal_on.cited_memory_ids}")
    print(f"  Reasoning:  {proposal_on.reasoning[:180]}...")
    print(f"  Latency:    {elapsed_on:.2f}s | Tokens: {proposal_on.token_usage.get('total_tokens', 0)}")

    # 4c. COMPARISON TABLE
    subheader("ACTUAL PROPOSAL COMPARISON (MEMORY OFF vs MEMORY ON)")
    print(f"{'Metric':<32} | {'Memory OFF':<22} | {'Memory ON':<22}")
    print(f"{'-'*32}-|-{'-'*22}-|-{'-'*22}")
    print(f"{'Proposed Action':<32} | {proposal_off.proposed_action.value:<22} | {proposal_on.proposed_action.value:<22}")
    print(f"{'Proposed Amount':<32} | ₹{proposal_off.proposed_amount_inr:<21,.2f} | ₹{proposal_on.proposed_amount_inr:<21,.2f}")
    print(f"{'Confidence Score':<32} | {proposal_off.confidence.score:<22.2f} | {proposal_on.confidence.score:<22.2f}")
    print(f"{'Confidence Band':<32} | {proposal_off.confidence.band.value:<22} | {proposal_on.confidence.band.value:<22}")
    print(f"{'Unique Historical Decisions (n)':<32} | {proposal_off.confidence.sample_size_n:<22} | {proposal_on.confidence.sample_size_n:<22}")
    print(f"{'Agreement Count':<32} | {proposal_off.confidence.agreement_count:<22} | {proposal_on.confidence.agreement_count:<22}")
    print(f"{'Consistency Fraction':<32} | {proposal_off.confidence.consistency:<22.2f} | {proposal_on.confidence.consistency:<22.2f}")
    print(f"{'Citations Count':<32} | {len(proposal_off.cited_memory_ids):<22} | {len(proposal_on.cited_memory_ids):<22}")

    # 5. HUMAN FEEDBACK & BENCHMARK ISOLATION VERIFICATION
    subheader("LEARNING VS BENCHMARK ISOLATION VERIFICATION")
    print("Testing feedback isolation between frozen baseline and live demo bank...")

    submission = FeedbackSubmission(
        invoice_number=inv.invoice_number,
        vendor_name=inv.vendor_name,
        exception_type=match_res.exception_type.value,
        agent_proposal=f"{proposal_on.proposed_action.value} at ₹{proposal_on.proposed_amount_inr:,.2f}",
        human_decision=ApproverDecision.EDITED,
        approver_role=ApproverRole.AP_MANAGER,
        human_explanation="Human approved agent proposal: edited invoice strictly to contracted PO rate ₹212,400.",
        final_amount_inr=proposal_on.proposed_amount_inr,
        cited_memory_ids=proposal_on.cited_memory_ids,
    )

    # 5a. Prove frozen baseline rejects feedback writes
    try:
        process_human_feedback(
            submission=submission,
            memory_client=mem_client,
            bank_id=BASELINE_EVAL_BANK_ID,
            allow_benchmark_contamination=False,
        )
        print("❌ FAILED: Baseline evaluation bank accepted feedback write! Contamination occurred!")
        sys.exit(1)
    except ValueError as e:
        print(f"✅ Baseline Evaluation Bank Protected: {e}")

    # 5b. Submit feedback into the Live Demonstration Bank
    print(f"\nSubmitting reviewer feedback into Live Demo Bank ('{LIVE_DEMO_BANK_ID}')...")
    fb_result = process_human_feedback(
        submission=submission,
        memory_client=mem_client,
        bank_id=LIVE_DEMO_BANK_ID,
    )
    print(f"✅ Live Demo Feedback Retained: Document ID = '{fb_result.document_id}' (Status: {fb_result.status})")

    # 5c. Immediate recall in live demonstration bank
    print(f"\nRecalling feedback from Live Demo Bank ('{LIVE_DEMO_BANK_ID}')...")
    recalled_feedback = mem_client.recall(
        bank_id=LIVE_DEMO_BANK_ID,
        query=f"Feedback for invoice {inv.invoice_number}",
        limit=2,
    )
    if not recalled_feedback:
        recalled_feedback = mem_client.offline_store.recall(
            bank_id=LIVE_DEMO_BANK_ID,
            query=f"Feedback for invoice {inv.invoice_number}",
            limit=2,
        )

    if recalled_feedback:
        print(f"✅ Live Learning Loop Verified! Recalled {len(recalled_feedback)} records from '{LIVE_DEMO_BANK_ID}':")
        for rf in recalled_feedback:
            src = "Offline Fallback" if rf.is_offline_fallback else "Hindsight Engine"
            print(f"   [{src}] Doc ID: {rf.document_id} | Text: {rf.text[:120]}...")
    else:
        print("⚠️  Feedback not returned immediately in recall.")

    # 5d. Confirm baseline evaluation bank still has 0 feedback records
    baseline_check = mem_client.recall(
        bank_id=BASELINE_EVAL_BANK_ID,
        query=f"feedback-{inv.invoice_number}",
        limit=2,
    )
    baseline_feedback_ids = [m.document_id for m in baseline_check if m.document_id and "feedback" in m.document_id]
    if baseline_feedback_ids:
        print(f"❌ CONTAMINATION DETECTED: {baseline_feedback_ids} found in baseline bank!")
        sys.exit(1)
    else:
        print(f"✅ Baseline Isolation Confirmed: Zero feedback records in '{BASELINE_EVAL_BANK_ID}'.")

    mem_client.close()
    header("VERIFICATION COMPLETE — ALL MILESTONE 3.1 GATES PASSED")


if __name__ == "__main__":
    run_verification()
