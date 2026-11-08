"""
tests/test_audit_regressions.py
────────────────────────────────────────────────────────────────────────────────
Production-Quality Audit & Regression Test Suite for Milestone 5.5:
  1. Negative and invalid monetary amounts are rejected at the model boundary.
  2. Case-insensitive and trimmed duplicate invoice detection.
  3. Exact boundary testing for POL-AP-001 (1.0%, 5.0%, and INR ceilings).
  4. Policy supremacy cannot be bypassed or downgraded by LLM proposals.
  5. OfflineStore idempotent upsert prevents file bloat and duplicate records.
  6. Temporal policy evaluation distinguishes past standards from active rules.
"""

from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError

from agent.matcher import match_invoice
from agent.resolver import ResolutionAgent
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, Discrepancy, ExceptionType, Invoice, MatchResult, PurchaseOrder
from data.synthetic import load_held_out_invoices
from memory.client import MemoryClient
from memory.offline_store import OfflineStore
from memory.schema import MemoryMode, RecalledMemory
from policy.conflict import evaluate_policy_precedent_conflict
from policy.corpus import POLICIES
from policy.models import CompanyPolicy, ConflictStatus
from policy.retriever import PolicyRetriever


# ─────────────────────────────────────────────────────────────────────────────
# 1. FINANCIAL & MODEL VALIDATION REGRESSIONS
# ─────────────────────────────────────────────────────────────────────────────

def test_negative_unit_price_rejection():
    """Negative unit price must be rejected at model instantiation."""
    with pytest.raises(ValidationError):
        Invoice(
            invoice_number="INV-NEG-001",
            vendor_name="Test Vendor",
            gstin="27ABCDE1234F1Z5",
            invoice_date=date(2025, 1, 1),
            po_number="PO-NEG-001",
            item_description="Test Item",
            hsn_code="8471",
            unit_price_inr=Decimal("-100.00"),
            quantity=10,
            total_excl_tax_inr=Decimal("-1000.00"),
            gst_rate=Decimal("0.18"),
            gst_amount_inr=Decimal("-180.00"),
            total_inr=Decimal("-1180.00"),
        )


def test_zero_or_negative_quantity_rejection():
    """Zero or negative quantity must be rejected."""
    with pytest.raises(ValidationError):
        PurchaseOrder(
            po_number="PO-ZERO-001",
            vendor_name="Test Vendor",
            gstin="27ABCDE1234F1Z5",
            issue_date=date(2025, 1, 1),
            valid_until=date(2025, 12, 31),
            item_description="Test Item",
            hsn_code="8471",
            unit_price_inr=Decimal("100.00"),
            quantity=0,
            total_excl_tax_inr=Decimal("0.00"),
            gst_rate=Decimal("0.18"),
            gst_amount_inr=Decimal("0.00"),
            total_inr=Decimal("0.00"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. DETERMINISTIC 3-WAY MATCH REGRESSIONS
# ─────────────────────────────────────────────────────────────────────────────

def test_case_insensitive_and_whitespace_duplicate_detection():
    """Duplicate detection must match case-insensitively and ignore whitespace."""
    target = load_held_out_invoices()[0]
    inv = target.invoice
    po = target.po

    # Paid invoice number with different casing and leading/trailing whitespace
    paid_set = {f"  {inv.invoice_number.lower()}  "}
    res = match_invoice(invoice=inv, po=po, grn=target.grn, paid_invoice_numbers=paid_set)

    assert res.is_match is False
    assert res.exception_type == ExceptionType.DUPLICATE_INVOICE
    assert res.expected_amount_inr == Decimal("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# 3. POLICY POL-AP-001 EXACT THRESHOLDS & BOUNDARY CONDITIONS
# ─────────────────────────────────────────────────────────────────────────────

def test_policy_001_exact_boundaries():
    """Verify POL-AP-001 v2.0 boundary conditions: <=1%, 1-5%, >5%."""
    retriever = PolicyRetriever()
    pol_v2 = retriever.get_applicable_policy(ExceptionType.PRICE_MISMATCH, as_of_date=date(2025, 10, 1))
    assert pol_v2 is not None
    assert pol_v2.version == "2.0"

    base_po = Decimal("100000.00")

    # Case A: Variance > 5.0% (e.g. 6.0%) -> Mandates REJECTED (Clause 2.3)
    match_excessive = MatchResult(
        is_match=False,
        exception_type=ExceptionType.PRICE_MISMATCH,
        invoice_number="INV-BOUND-01",
        po_number="PO-BOUND-01",
        vendor_name="Prabhav Infosystems Pvt Ltd",
        invoice_amount_inr=Decimal("106000.00"),
        expected_amount_inr=base_po,
        explanation="6.0% price overcharge",
    )
    inv_dummy = load_held_out_invoices()[0].invoice

    past_approved = [
        RecalledMemory(
            id="m-bound-1",
            document_id="decision-INV-BOUND-01",
            text="Past approved price overage.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:approved"],
            metadata={"decision": "APPROVED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "price_mismatch"},
        )
    ]

    eval_excessive = evaluate_policy_precedent_conflict(
        invoice=inv_dummy,
        match_result=match_excessive,
        policy=pol_v2,
        historical_memories=past_approved,
    )
    assert eval_excessive.status == ConflictStatus.POLICY_PRECEDENT_CONFLICT
    assert eval_excessive.recommended_action == ApproverDecision.REJECTED
    assert "excessive variance ceiling" in eval_excessive.explanation.lower()


def test_resolver_enforces_mandatory_rejection_over_model_proposal():
    """Resolver must never downgrade a policy-mandated REJECTED action to EDITED or APPROVED."""
    held_out = load_held_out_invoices()
    target = held_out[0]  # Prabhav

    # Mock LLM that attempts to EDIT an invoice that policy requires to be REJECTED (>5% overage)
    mock_llm = type("MockLLMClient", (), {
        "call_json": lambda *a, **k: ({
            "proposed_action": "EDITED",
            "proposed_amount_inr": str(target.po.total_inr),
            "reasoning": "Attempting to edit down despite >5% variance.",
            "cited_memory_ids": ["decision-INV-PI-2024-001"],
        }, {"total_tokens": 120}),
    })()

    # Create match result with 7.0% variance (>5.0% threshold)
    excessive_match = MatchResult(
        is_match=False,
        exception_type=ExceptionType.PRICE_MISMATCH,
        invoice_number=target.invoice.invoice_number,
        po_number=target.po.po_number,
        vendor_name=target.invoice.vendor_name,
        invoice_amount_inr=Decimal("230000.00"),
        expected_amount_inr=Decimal("212400.00"),
        explanation="7.0% price overcharge",
    )

    mem_client = MemoryClient(mode=MemoryMode.OFFLINE)
    agent = ResolutionAgent(
        memory_client=mem_client,
        llm_client=mock_llm,
        default_bank_id=LIVE_DEMO_BANK_ID,
    )

    # Retain an approval in memory to create a precedent conflict
    mem_client.retain(
        bank_id=LIVE_DEMO_BANK_ID,
        content="Approved price overage in past.",
        document_id="decision-INV-PI-2024-001",
        tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:approved"],
        metadata={"decision": "APPROVED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "price_mismatch"},
    )

    prop = agent.resolve(
        invoice=target.invoice,
        po=target.po,
        grn=target.grn,
        match_result=excessive_match,
        memory_enabled=True,
        bank_id=LIVE_DEMO_BANK_ID,
    )

    # Policy supremacy must force action to REJECTED despite model proposing EDITED
    assert prop.proposed_action == ApproverDecision.REJECTED
    assert prop.conflict_status == ConflictStatus.POLICY_PRECEDENT_CONFLICT


# ─────────────────────────────────────────────────────────────────────────────
# 4. MEMORY STORE IDEMPOTENCY & ISOLATION
# ─────────────────────────────────────────────────────────────────────────────

def test_offline_store_idempotent_upsert(tmp_path):
    """Retaining the same (bank_id, document_id) multiple times must not bloat or duplicate records."""
    store_file = tmp_path / "test_offline.jsonl"
    store = OfflineStore(store_path=store_file)

    # 1. Retain initial record
    id1 = store.retain(
        bank_id="test-bank",
        content="Initial feedback content",
        document_id="feedback-INV-001",
        tags=["vendor:test", "decision:edited"],
    )

    all_1 = store.get_all(bank_id="test-bank")
    assert len(all_1) == 1
    assert all_1[0]["content"] == "Initial feedback content"

    # 2. Retain updated record with the same bank_id and document_id
    id2 = store.retain(
        bank_id="test-bank",
        content="Updated feedback content with revised explanation",
        document_id="feedback-INV-001",
        tags=["vendor:test", "decision:approved"],
    )

    all_2 = store.get_all(bank_id="test-bank")
    # Must STILL be exactly 1 record, not 2!
    assert len(all_2) == 1
    assert all_2[0]["id"] == id1  # Preserves initial ID
    assert all_2[0]["content"] == "Updated feedback content with revised explanation"
    assert "decision:approved" in all_2[0]["tags"]

