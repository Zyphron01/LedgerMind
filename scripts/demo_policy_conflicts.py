"""
scripts/demo_policy_conflicts.py
────────────────────────────────────────────────────────────────────────────────
Milestone 5 Demonstration Script: Policy RAG & Policy-Precedent Conflict Detection.
Demonstrates the three reproducible benchmark scenarios:
  1. SCENARIO A: Consistent Precedent (COMPLIANT_PRECEDENT)
  2. SCENARIO B: Policy Conflict (POLICY_PRECEDENT_CONFLICT)
  3. SCENARIO C: Policy Version Change (POLICY_VERSION_CHANGED)
"""

from decimal import Decimal
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ROOT_DIR / ".env")
except Exception:
    pass

from agent.resolver import ResolutionAgent
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, HeldOutInvoice
from data.synthetic import load_held_out_invoices
from memory.client import MemoryClient
from memory.schema import MemoryMode, RecalledMemory
from policy.conflict import evaluate_policy_precedent_conflict
from policy.models import ConflictStatus
from policy.retriever import PolicyRetriever


def print_banner(title: str) -> None:
    sep = "═" * 78
    print(f"\n{sep}\n  {title}\n{sep}")


def print_section(title: str) -> None:
    sep = "─" * 78
    print(f"\n{sep}\n  {title}\n{sep}")


def run_demo_scenarios(client_mode: str = "offline") -> None:
    print_banner("LEDGERMIND MILESTONE 5/6: POLICY RAG & CONFLICT DETECTION BENCHMARK")
    print(f"• Execution Mode: {client_mode.upper()}")

    held_out = load_held_out_invoices()
    retriever = PolicyRetriever()

    # Deterministic LLM responder that simulates the approver proposal for each scenario
    class DemoLLMClient:
        def __init__(self):
            self.scenario = "A"

        def call_json(self, messages, temperature=0.0, max_tokens=1536):
            if self.scenario == "A":
                return {
                    "proposed_action": "EDITED",
                    "proposed_amount_inr": "212400.00",
                    "reasoning": "Edited unit rate to contracted PO rate per POL-AP-001 v2.0 Clause 2.2 and consistent historical precedents.",
                    "cited_memory_ids": ["decision-INV-PI-2024-001", "decision-INV-PI-2024-002"],
                }, {"total_tokens": 160}
            elif self.scenario == "B":
                # Simulated attempt by LLM to follow past informal approvals
                return {
                    "proposed_action": "APPROVED",
                    "proposed_amount_inr": "132600.00",
                    "reasoning": "Proposed approval following past approver precedent for raw cotton variance.",
                    "cited_memory_ids": ["decision-INV-BTT-2024-001", "decision-INV-BTT-2024-002"],
                }, {"total_tokens": 150}
            else:
                # Simulated attempt by LLM to follow retired v1.0 grace period
                return {
                    "proposed_action": "APPROVED",
                    "proposed_amount_inr": "188800.00",
                    "reasoning": "Proposed approval under historical grace extension precedent.",
                    "cited_memory_ids": ["decision-INV-SEW-2024-001"],
                }, {"total_tokens": 140}

    POLICY_DEMO_BANK_ID = "ledgermind-policy-conflicts-demo"
    demo_llm = DemoLLMClient()
    mem_mode = MemoryMode(client_mode)
    mem_client = MemoryClient(mode=mem_mode)
    agent = ResolutionAgent(memory_client=mem_client, llm_client=demo_llm, default_bank_id=POLICY_DEMO_BANK_ID, policy_retriever=retriever)

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO A — Consistent Precedent (COMPLIANT_PRECEDENT)
    # ─────────────────────────────────────────────────────────────────────────
    print_section("SCENARIO A — CONSISTENT PRECEDENT (Prabhav Infosystems)")
    inv_a: HeldOutInvoice = held_out[0]  # INV-PI-2025-101
    print(f"• Invoice Number: {inv_a.invoice.invoice_number} ({inv_a.invoice.vendor_name})")
    print(f"• Billed Unit Price: ₹{inv_a.invoice.unit_price_inr:,.2f} vs PO Unit Price: ₹{inv_a.po.unit_price_inr:,.2f}")
    print(f"• Total Billed: ₹{inv_a.invoice.total_inr:,.2f} (PO Contracted: ₹{inv_a.po.total_inr:,.2f})")
    print(f"• Discrepancy: {inv_a.match_result.exception_type.value} — {inv_a.match_result.explanation}")

    # Retain realistic consistent precedents into bank
    mem_client.retain(
        bank_id=POLICY_DEMO_BANK_ID,
        content="Invoice INV-PI-2024-001 from Prabhav Infosystems. Decision: EDITED down to contracted PO rate.",
        document_id="decision-INV-PI-2024-001",
        tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
        metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "price_mismatch"},
    )
    mem_client.retain(
        bank_id=POLICY_DEMO_BANK_ID,
        content="Invoice INV-PI-2024-002 from Prabhav Infosystems. Decision: EDITED to contracted PO total.",
        document_id="decision-INV-PI-2024-002",
        tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
        metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "price_mismatch"},
    )

    prop_a = agent.resolve(
        invoice=inv_a.invoice,
        po=inv_a.po,
        grn=inv_a.grn,
        match_result=inv_a.match_result,
        memory_enabled=True,
        bank_id=POLICY_DEMO_BANK_ID,
    )

    print(f"\n[GOVERNING POLICY]")
    print(f"  Policy ID:     {prop_a.policy_id} (Version {prop_a.policy_version})")
    print(f"  Title:         {prop_a.policy_title}")
    print(f"  Quoted Clause: \"{prop_a.quoted_clause}\"")
    print(f"\n[CONFLICT EVALUATION]")
    print(f"  Conflict Status:     {prop_a.conflict_status.value}")
    print(f"  Requires Escalation: {prop_a.requires_escalation}")
    print(f"  Evaluation Finding:  {prop_a.conflict_explanation}")
    print(f"\n[AGENT PROPOSAL]")
    print(f"  Proposed Action:     {prop_a.proposed_action.value}")
    print(f"  Proposed Amount:     ₹{prop_a.proposed_amount_inr:,.2f}")
    print(f"  Precedent Citations: {prop_a.cited_memory_ids}")
    print(f"  Confidence:          {prop_a.confidence.score:.2f} ({prop_a.confidence.band.value}) [n={prop_a.confidence.sample_size_n}]")

    assert prop_a.conflict_status == ConflictStatus.COMPLIANT_PRECEDENT
    assert prop_a.proposed_action == ApproverDecision.EDITED
    assert prop_a.requires_escalation is False

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO B — Policy Conflict (POLICY_PRECEDENT_CONFLICT)
    # ─────────────────────────────────────────────────────────────────────────
    print_section("SCENARIO B — POLICY–PRECEDENT CONFLICT (Bhavna Textile Traders)")
    demo_llm.scenario = "B"
    inv_b: HeldOutInvoice = next(i for i in held_out if i.invoice.invoice_number == "INV-BTT-2025-101")
    print(f"• Invoice Number: {inv_b.invoice.invoice_number} ({inv_b.invoice.vendor_name})")
    print(f"• Total Billed: ₹{inv_b.invoice.total_inr:,.2f} vs PO Contracted: ₹{inv_b.po.total_inr:,.2f}")
    variance_pct = (abs(inv_b.invoice.total_inr - inv_b.po.total_inr) / inv_b.po.total_inr * 100)
    print(f"• Discrepancy: {inv_b.match_result.exception_type.value} (+{variance_pct:.2f}% price variance)")

    # Retain unauthorized informal approvals where human approvers allowed price overage
    mem_client.retain(
        bank_id=POLICY_DEMO_BANK_ID,
        content="Invoice INV-BTT-2024-001 from Bhavna Textile Traders. Approved price variance (+2.8%) without PO amendment.",
        document_id="decision-INV-BTT-2024-001",
        tags=["vendor:bhavna-textiles", "exception:price_mismatch", "decision:approved"],
        metadata={"decision": "APPROVED", "vendor_name": "Bhavna Textile Traders", "exception_type": "price_mismatch"},
    )
    mem_client.retain(
        bank_id=POLICY_DEMO_BANK_ID,
        content="Invoice INV-BTT-2024-002 from Bhavna Textile Traders. Approved price overage (+2.5%) based on cotton index.",
        document_id="decision-INV-BTT-2024-002",
        tags=["vendor:bhavna-textiles", "exception:price_mismatch", "decision:approved"],
        metadata={"decision": "APPROVED", "vendor_name": "Bhavna Textile Traders", "exception_type": "price_mismatch"},
    )

    prop_b = agent.resolve(
        invoice=inv_b.invoice,
        po=inv_b.po,
        grn=inv_b.grn,
        match_result=inv_b.match_result,
        memory_enabled=True,
        bank_id=POLICY_DEMO_BANK_ID,
    )

    print(f"\n[GOVERNING POLICY]")
    print(f"  Policy ID:     {prop_b.policy_id} (Version {prop_b.policy_version})")
    print(f"  Title:         {prop_b.policy_title}")
    print(f"  Quoted Clause: \"{prop_b.quoted_clause}\"")
    print(f"\n[CONFLICT EVALUATION]")
    print(f"  Conflict Status:     {prop_b.conflict_status.value}")
    print(f"  Requires Escalation: {prop_b.requires_escalation}")
    print(f"  Escalation Path:     {prop_b.escalation_path}")
    print(f"  Evaluation Finding:  {prop_b.conflict_explanation}")
    print(f"\n[AGENT PROPOSAL - POLICY SUPREMACY ENFORCED]")
    print(f"  Proposed Action:     {prop_b.proposed_action.value} (Overrode unauthorized historical 'APPROVED' precedent)")
    print(f"  Precedent Citations: {prop_b.cited_memory_ids}")
    print(f"  Confidence:          {prop_b.confidence.score:.2f} ({prop_b.confidence.band.value}) [n={prop_b.confidence.sample_size_n}]")

    assert prop_b.conflict_status == ConflictStatus.POLICY_PRECEDENT_CONFLICT
    assert prop_b.proposed_action == ApproverDecision.ESCALATED
    assert prop_b.requires_escalation is True

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO C — Policy Version Change (POLICY_VERSION_CHANGED)
    # ─────────────────────────────────────────────────────────────────────────
    print_section("SCENARIO C — POLICY VERSION SHIFT (Suryakant Engineering Works)")
    demo_llm.scenario = "C"
    inv_c: HeldOutInvoice = next(i for i in held_out if i.invoice.invoice_number == "INV-SEW-2025-101")
    print(f"• Invoice Number: {inv_c.invoice.invoice_number} ({inv_c.invoice.vendor_name})")
    print(f"• Invoice Date: {inv_c.invoice.invoice_date} (PO Validity Expired: {inv_c.po.valid_until})")
    print(f"• Discrepancy: {inv_c.match_result.exception_type.value} — {inv_c.match_result.explanation}")

    # Retain older historical decisions under retired v1.0 grace period
    mem_client.retain(
        bank_id=POLICY_DEMO_BANK_ID,
        content="Invoice INV-SEW-2024-001. Approved under 30-day grace extension by AP Manager.",
        document_id="decision-INV-SEW-2024-001",
        tags=["vendor:suryakant-engineering", "exception:po_expired", "decision:approved"],
        metadata={"decision": "APPROVED", "vendor_name": "Suryakant Engineering Works", "exception_type": "po_expired"},
    )

    prop_c = agent.resolve(
        invoice=inv_c.invoice,
        po=inv_c.po,
        grn=inv_c.grn,
        match_result=inv_c.match_result,
        memory_enabled=True,
        bank_id=POLICY_DEMO_BANK_ID,
    )

    print(f"\n[GOVERNING POLICY]")
    print(f"  Policy ID:     {prop_c.policy_id} (Version {prop_c.policy_version})")
    print(f"  Title:         {prop_c.policy_title}")
    print(f"  Quoted Clause: \"{prop_c.quoted_clause}\"")
    print(f"\n[CONFLICT EVALUATION]")
    print(f"  Conflict Status:     {prop_c.conflict_status.value}")
    print(f"  Requires Escalation: {prop_c.requires_escalation}")
    print(f"  Evaluation Finding:  {prop_c.conflict_explanation}")
    print(f"\n[AGENT PROPOSAL - CURRENT POLICY SUPREMACY ENFORCED]")
    print(f"  Proposed Action:     {prop_c.proposed_action.value} (Strict Rejection under Policy 2025-Q3; retired grace ignored)")
    print(f"  Precedent Citations: {prop_c.cited_memory_ids}")
    print(f"  Confidence:          {prop_c.confidence.score:.2f} ({prop_c.confidence.band.value}) [n={prop_c.confidence.sample_size_n}]")

    assert prop_c.conflict_status == ConflictStatus.POLICY_VERSION_CHANGED
    assert prop_c.proposed_action == ApproverDecision.REJECTED

    print_banner("ALL THREE BENCHMARK SCENARIOS VERIFIED SUCCESSFULLY!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run policy conflict demonstration scenarios.")
    parser.add_argument("--mode", default="offline", choices=["offline", "local", "cloud"])
    args = parser.parse_args()
    run_demo_scenarios(client_mode=args.mode)
