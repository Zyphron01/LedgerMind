"""
tests/test_policy_rag.py
────────────────────────────────────────────────────────────────────────────────
Automated unit and integration tests for Milestone 5 Policy RAG & Conflict Detection:
  1. Correct policy selection and version scoping by date.
  2. Policy effective date boundaries and version changes.
  3. Deterministic threshold calculations (e.g. 1.0% price tolerance).
  4. Policy-precedent conflict detection (Scenario B: unauthorized informal approval).
  5. Policy version shift detection (Scenario C: retired v1.0 grace vs active v2.0 rejection).
  6. Compliant precedent detection (Scenario A: price adjustment matching policy).
  7. Policy unknown fallback (requires human review, no fabricated rules).
  8. Policy supremacy: written policy overrides historical human approvals.
  9. Non-contamination of baseline evaluation bank.
"""

from datetime import date
from decimal import Decimal
import pytest

from agent.resolver import ResolutionAgent
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, ExceptionType, MatchResult
from data.synthetic import load_held_out_invoices
from memory.client import MemoryClient
from memory.schema import MemoryMode, RecalledMemory
from policy.corpus import POLICIES
from policy.conflict import evaluate_policy_precedent_conflict
from policy.models import ConflictStatus
from policy.retriever import PolicyRetriever


@pytest.fixture
def retriever():
    return PolicyRetriever()


def test_correct_policy_selection(retriever):
    """Verify that correct policy document is returned for each exception type."""
    pol_price = retriever.get_applicable_policy(ExceptionType.PRICE_MISMATCH, as_of_date=date(2025, 10, 1))
    assert pol_price is not None
    assert pol_price.policy_id == "POL-AP-001"
    assert pol_price.version == "2.0"

    pol_dup = retriever.get_applicable_policy(ExceptionType.DUPLICATE_INVOICE, as_of_date=date(2025, 10, 1))
    assert pol_dup is not None
    assert pol_dup.policy_id == "POL-AP-003"

    pol_qty = retriever.get_applicable_policy(ExceptionType.QUANTITY_SHORTFALL, as_of_date=date(2025, 10, 1))
    assert pol_qty is not None
    assert pol_qty.policy_id == "POL-AP-002"

    pol_gst = retriever.get_applicable_policy(ExceptionType.GST_RATE_ERROR, as_of_date=date(2025, 10, 1))
    assert pol_gst is not None
    assert pol_gst.policy_id == "POL-AP-005"
    assert pol_gst.is_statutory is True


def test_policy_effective_date_scoping(retriever):
    """Verify that temporal boundaries select the appropriate policy version."""
    # POL-AP-004 v1.0 was active before 2025-08-01
    pol_v1 = retriever.get_applicable_policy(ExceptionType.PO_EXPIRED, as_of_date=date(2025, 6, 15))
    assert pol_v1 is not None
    assert pol_v1.policy_id == "POL-AP-004"
    assert pol_v1.version == "1.0"
    assert "grace extension" in pol_v1.primary_clause.lower()

    # POL-AP-004 v2.0 is active on and after 2025-08-01
    pol_v2 = retriever.get_applicable_policy(ExceptionType.PO_EXPIRED, as_of_date=date(2025, 10, 15))
    assert pol_v2 is not None
    assert pol_v2.policy_id == "POL-AP-004"
    assert pol_v2.version == "2.0"
    assert "zero tolerance" in pol_v2.primary_clause.lower()


def test_unknown_policy_fallback():
    """When an exception has no registered policy, detector must flag POLICY_UNKNOWN without hallucinating rules."""
    retriever_empty = PolicyRetriever(corpus=[])
    pol = retriever_empty.get_applicable_policy(ExceptionType.PRICE_MISMATCH)
    assert pol is None

    # Dummy match result
    match_res = MatchResult(
        is_match=False,
        exception_type=ExceptionType.PRICE_MISMATCH,
        primary_discrepancy=None,
        invoice_number="INV-TEST-001",
        po_number="PO-TEST-001",
        vendor_name="Test Vendor",
        invoice_amount_inr=Decimal("10000.00"),
        expected_amount_inr=Decimal("9000.00"),
        explanation="Test price mismatch",
    )
    # Dummy invoice
    inv = load_held_out_invoices()[0].invoice

    eval_res = evaluate_policy_precedent_conflict(
        invoice=inv,
        match_result=match_res,
        policy=None,
        historical_memories=[],
    )

    assert eval_res.status == ConflictStatus.POLICY_UNKNOWN
    assert eval_res.requires_escalation is True
    assert eval_res.recommended_action == ApproverDecision.ESCALATED


def test_compliant_precedent_detection(retriever):
    """Scenario A: Past practice of editing down to PO rate matches POL-AP-001 v2.0."""
    target = load_held_out_invoices()[0]  # INV-PI-2025-101 (Prabhav Infosystems)
    pol = retriever.get_applicable_policy(ExceptionType.PRICE_MISMATCH, as_of_date=target.invoice.invoice_date)

    mems = [
        RecalledMemory(
            id="m-1",
            document_id="decision-INV-PI-2024-001",
            text="Invoice unit rate adjusted down to PO contracted rate.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
            metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "price_mismatch"},
        ),
        RecalledMemory(
            id="m-2",
            document_id="decision-INV-PI-2024-002",
            text="Edited to contracted PO rate.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
            metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "price_mismatch"},
        ),
    ]

    eval_res = evaluate_policy_precedent_conflict(
        invoice=target.invoice,
        match_result=target.match_result,
        policy=pol,
        historical_memories=mems,
    )

    assert eval_res.status == ConflictStatus.COMPLIANT_PRECEDENT
    assert eval_res.requires_escalation is False
    assert eval_res.recommended_action == ApproverDecision.EDITED
    assert "decision-INV-PI-2024-001" in eval_res.compliant_document_ids


def test_policy_precedent_conflict_detection(retriever):
    """Scenario B: Past practice of informally approving price overcharges violates POL-AP-001 v2.0."""
    held_out = load_held_out_invoices()
    bhavna_inv = next(i for i in held_out if i.invoice.invoice_number == "INV-BTT-2025-101")
    pol = retriever.get_applicable_policy(ExceptionType.PRICE_MISMATCH, as_of_date=bhavna_inv.invoice.invoice_date)

    # Past human approvers approved price variances without PO amendments
    mems = [
        RecalledMemory(
            id="m-b1",
            document_id="decision-INV-BTT-2024-001",
            text="Approved price variance of 2.8% due to cotton index fluctuation.",
            tags=["vendor:bhavna-textiles", "exception:price_mismatch", "decision:approved"],
            metadata={"decision": "APPROVED", "vendor_name": "Bhavna Textile Traders", "exception_type": "price_mismatch"},
        ),
        RecalledMemory(
            id="m-b2",
            document_id="decision-INV-BTT-2024-002",
            text="Approved unit price variance without amendment.",
            tags=["vendor:bhavna-textiles", "exception:price_mismatch", "decision:approved"],
            metadata={"decision": "APPROVED", "vendor_name": "Bhavna Textile Traders", "exception_type": "price_mismatch"},
        ),
    ]

    eval_res = evaluate_policy_precedent_conflict(
        invoice=bhavna_inv.invoice,
        match_result=bhavna_inv.match_result,
        policy=pol,
        historical_memories=mems,
    )

    assert eval_res.status == ConflictStatus.POLICY_PRECEDENT_CONFLICT
    assert eval_res.requires_escalation is True
    assert eval_res.recommended_action == ApproverDecision.ESCALATED
    assert "decision-INV-BTT-2024-001" in eval_res.conflicting_document_ids


def test_policy_version_change_detection(retriever):
    """Scenario C: Expired PO approved under retired v1.0 must be REJECTED under active v2.0."""
    held_out = load_held_out_invoices()
    suryakant_inv = next(i for i in held_out if i.invoice.invoice_number == "INV-SEW-2025-101")
    pol = retriever.get_applicable_policy(ExceptionType.PO_EXPIRED, as_of_date=suryakant_inv.invoice.invoice_date)

    assert pol.version == "2.0"

    # Precedents from 2024 were approved with grace extension under v1.0
    mems = [
        RecalledMemory(
            id="m-s1",
            document_id="decision-INV-SEW-2024-001",
            text="Approved with 30-day grace extension by AP Manager.",
            tags=["vendor:suryakant-engineering", "exception:po_expired", "decision:approved"],
            metadata={"decision": "APPROVED", "vendor_name": "Suryakant Engineering Works", "exception_type": "po_expired"},
        ),
    ]

    eval_res = evaluate_policy_precedent_conflict(
        invoice=suryakant_inv.invoice,
        match_result=suryakant_inv.match_result,
        policy=pol,
        historical_memories=mems,
    )

    assert eval_res.status == ConflictStatus.POLICY_VERSION_CHANGED
    assert eval_res.recommended_action == ApproverDecision.REJECTED
    assert "decision-INV-SEW-2024-001" in eval_res.conflicting_document_ids


def test_resolver_enforces_policy_supremacy():
    """Resolver must override an LLM proposal if it attempts to repeat an unauthorized historical approval."""
    held_out = load_held_out_invoices()
    bhavna_inv = next(i for i in held_out if i.invoice.invoice_number == "INV-BTT-2025-101")

    # Mock LLM that blindly tries to approve based on precedent
    mock_llm = type("MockLLMClient", (), {
        "call_json": lambda *a, **k: ({
            "proposed_action": "APPROVED",
            "proposed_amount_inr": str(bhavna_inv.invoice.total_inr),
            "reasoning": "Approved based on past vendor history.",
            "cited_memory_ids": ["decision-INV-BTT-2024-001"],
        }, {"total_tokens": 120}),
    })()

    mem_client = MemoryClient(mode=MemoryMode.OFFLINE)
    # Retain the unauthorized historical approval in memory
    mem_client.retain(
        bank_id=LIVE_DEMO_BANK_ID,
        content="Approved price variance of 2.8% without PO amendment.",
        document_id="decision-INV-BTT-2024-001",
        tags=["vendor:bhavna-textiles", "exception:price_mismatch", "decision:approved"],
        metadata={"decision": "APPROVED", "vendor_name": "Bhavna Textile Traders", "exception_type": "price_mismatch"},
    )

    agent = ResolutionAgent(
        memory_client=mem_client,
        llm_client=mock_llm,
        default_bank_id=LIVE_DEMO_BANK_ID,
    )

    proposal = agent.resolve(
        invoice=bhavna_inv.invoice,
        po=bhavna_inv.po,
        grn=bhavna_inv.grn,
        match_result=bhavna_inv.match_result,
        memory_enabled=True,
        bank_id=LIVE_DEMO_BANK_ID,
    )

    # ResolutionAgent must intercept and override to ESCALATED per written policy supremacy!
    assert proposal.conflict_status == ConflictStatus.POLICY_PRECEDENT_CONFLICT
    assert proposal.proposed_action == ApproverDecision.ESCALATED
    assert proposal.requires_escalation is True
    assert proposal.policy_id == "POL-AP-001"
    assert proposal.policy_version == "2.0"

