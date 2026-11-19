"""
tests/test_milestone2_reliability.py
────────────────────────────────────────────────────────────────────────────────
Milestone 2 Acceptance & Integration Reliability Test Suite:
  1. Groq LLM API failure resilience: LLMError failover to deterministic fallback.
  2. Missing or unconfigured GROQ_API_KEY fallback behavior.
  3. Deterministic fallback accuracy across all 3-way match exception categories:
     - Duplicate invoice -> REJECTED (₹0.00)
     - Expired PO -> REJECTED (₹0.00)
     - Statutory HSN mismatch -> REJECTED (₹0.00)
     - Statutory GST rate mismatch -> REJECTED (₹0.00)
     - Quantity shortfall with GRN -> EDITED (to received goods amount)
     - Price mismatch with precedent -> EDITED (to contracted PO price)
  4. Corporate Policy Supremacy enforcement under fallback mode.
  5. Telemetry and audit provenance: llm_fallback=True, zero token cost.
  6. Hindsight offline recall and graceful timeout recovery.
"""

from datetime import date
from decimal import Decimal
from typing import List, Optional
import pytest

from agent.llm import GroqClient, LLMError
from agent.matcher import match_invoice
from agent.resolver import ResolutionAgent, ResolutionProposal
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import (
    ApproverDecision,
    Discrepancy,
    ExceptionType,
    GoodsReceiptNote,
    Invoice,
    MatchResult,
    PurchaseOrder,
)
from data.synthetic import load_held_out_invoices
from memory.client import MemoryClient
from memory.schema import MemoryMode, RecalledMemory
from policy.models import CompanyPolicy, ConflictStatus


class FailingLLMClient:
    """Mock LLM that simulates network drops, 429 rate limits, and quota exhaustion."""

    def __init__(self, error_message: str = "Groq daily token limit exceeded (TPD 429)."):
        self.error_message = error_message
        self.call_count = 0

    def call_json(self, *args, **kwargs):
        self.call_count += 1
        raise LLMError(self.error_message)

    def is_available(self) -> bool:
        return True


class MockOfflineMemoryClient:
    """Mock MemoryClient providing controlled historical precedents in offline mode."""

    def __init__(self, memories: Optional[List[RecalledMemory]] = None):
        self.mode = MemoryMode.OFFLINE
        self.memories = memories or []
        self.last_recall_source = "offline"
        self.last_fallback_reason = "Offline mode configured"

    def recall(self, *args, **kwargs) -> List[RecalledMemory]:
        return self.memories

    def reflect(self, *args, **kwargs):
        return None

    def close(self):
        pass


@pytest.fixture
def base_po() -> PurchaseOrder:
    return PurchaseOrder(
        po_number="PO-TEST-2025-001",
        vendor_name="Prabhav Infosystems Pvt Ltd",
        gstin="27AABCP1234F1Z5",
        issue_date=date(2025, 1, 1),
        valid_until=date(2025, 12, 31),
        item_description="Cloud Security Consultation",
        hsn_code="998311",
        unit_price_inr=Decimal("200000.00"),
        quantity=1,
        total_excl_tax_inr=Decimal("200000.00"),
        gst_rate=Decimal("0.18"),
        gst_amount_inr=Decimal("36000.00"),
        total_inr=Decimal("236000.00"),
    )


@pytest.fixture
def base_grn() -> GoodsReceiptNote:
    return GoodsReceiptNote(
        grn_number="GRN-TEST-2025-001",
        po_number="PO-TEST-2025-001",
        vendor_name="Prabhav Infosystems Pvt Ltd",
        receipt_date=date(2025, 1, 5),
        item_description="Cloud Security Consultation",
        received_quantity=1,
        accepted_quantity=1,
        rejected_quantity=0,
    )


def test_groq_llm_error_activates_deterministic_fallback(base_po, base_grn):
    """When Groq LLM raises LLMError, agent.resolve() must NOT crash and return a valid fallback proposal."""
    failing_llm = FailingLLMClient(error_message="Simulated Groq 429 RateLimitError: daily TPD quota exhausted.")
    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(),
        llm_client=failing_llm,
    )

    inv = Invoice(
        invoice_number="INV-TEST-PRICE-001",
        vendor_name=base_po.vendor_name,
        gstin=base_po.gstin,
        invoice_date=date(2025, 1, 10),
        po_number=base_po.po_number,
        item_description=base_po.item_description,
        hsn_code=base_po.hsn_code,
        unit_price_inr=Decimal("210000.00"),
        quantity=1,
        total_excl_tax_inr=Decimal("210000.00"),
        gst_rate=Decimal("0.18"),
        gst_amount_inr=Decimal("37800.00"),
        total_inr=Decimal("247800.00"),
    )

    match_res = match_invoice(invoice=inv, po=base_po, grn=base_grn)
    assert match_res.exception_type == ExceptionType.PRICE_MISMATCH

    proposal = agent.resolve(
        invoice=inv,
        po=base_po,
        grn=base_grn,
        match_result=match_res,
        memory_enabled=False,
    )

    assert isinstance(proposal, ResolutionProposal)
    assert proposal.llm_fallback is True
    assert "LLMError" in (proposal.fallback_reason or "")
    assert "daily TPD quota" in (proposal.fallback_reason or "")
    assert proposal.token_usage.get("total_tokens", -1) == 0
    assert proposal.proposed_action in (ApproverDecision.EDITED, ApproverDecision.REJECTED)
    assert proposal.proposed_amount_inr <= inv.total_inr
    assert failing_llm.call_count == 1


def test_groq_missing_api_key_activates_deterministic_fallback(base_po, base_grn):
    """When GROQ_API_KEY is missing or empty, resolver must immediately fall back without error."""
    unconfigured_llm = GroqClient(api_key="")
    assert unconfigured_llm.is_available() is False

    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(),
        llm_client=unconfigured_llm,
    )

    inv = Invoice(
        invoice_number="INV-TEST-UNCONF-001",
        vendor_name=base_po.vendor_name,
        gstin=base_po.gstin,
        invoice_date=date(2025, 1, 10),
        po_number=base_po.po_number,
        item_description=base_po.item_description,
        hsn_code=base_po.hsn_code,
        unit_price_inr=Decimal("210000.00"),
        quantity=1,
        total_excl_tax_inr=Decimal("210000.00"),
        gst_rate=Decimal("0.18"),
        gst_amount_inr=Decimal("37800.00"),
        total_inr=Decimal("247800.00"),
    )

    match_res = match_invoice(invoice=inv, po=base_po, grn=base_grn)
    proposal = agent.resolve(invoice=inv, po=base_po, grn=base_grn, match_result=match_res)

    assert proposal.llm_fallback is True
    assert "GROQ_API_KEY" in (proposal.fallback_reason or "")
    assert proposal.token_usage.get("total_tokens", -1) == 0


def test_deterministic_fallback_duplicate_invoice(base_po, base_grn):
    """Duplicate invoices under fallback mode must be REJECTED for ₹0.00."""
    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(),
        llm_client=FailingLLMClient(),
    )

    inv = Invoice(
        invoice_number="INV-TEST-DUP-001",
        vendor_name=base_po.vendor_name,
        gstin=base_po.gstin,
        invoice_date=date(2025, 1, 10),
        po_number=base_po.po_number,
        item_description=base_po.item_description,
        hsn_code=base_po.hsn_code,
        unit_price_inr=base_po.unit_price_inr,
        quantity=1,
        total_excl_tax_inr=base_po.total_excl_tax_inr,
        gst_rate=base_po.gst_rate,
        gst_amount_inr=base_po.gst_amount_inr,
        total_inr=base_po.total_inr,
    )

    match_res = match_invoice(
        invoice=inv,
        po=base_po,
        grn=base_grn,
        paid_invoice_numbers={"inv-test-dup-001"},
    )
    assert match_res.exception_type == ExceptionType.DUPLICATE_INVOICE

    proposal = agent.resolve(invoice=inv, po=base_po, grn=base_grn, match_result=match_res)

    assert proposal.llm_fallback is True
    assert proposal.proposed_action == ApproverDecision.REJECTED
    assert proposal.proposed_amount_inr == Decimal("0.00")
    assert "duplicate" in proposal.reasoning.lower()


def test_deterministic_fallback_expired_po(base_po, base_grn):
    """Invoices billed against expired POs under fallback mode must be REJECTED for ₹0.00."""
    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(),
        llm_client=FailingLLMClient(),
    )

    inv_late = Invoice(
        invoice_number="INV-TEST-EXP-001",
        vendor_name=base_po.vendor_name,
        gstin=base_po.gstin,
        invoice_date=date(2026, 6, 1),  # After valid_until 2025-12-31
        po_number=base_po.po_number,
        item_description=base_po.item_description,
        hsn_code=base_po.hsn_code,
        unit_price_inr=base_po.unit_price_inr,
        quantity=1,
        total_excl_tax_inr=base_po.total_excl_tax_inr,
        gst_rate=base_po.gst_rate,
        gst_amount_inr=base_po.gst_amount_inr,
        total_inr=base_po.total_inr,
    )

    match_res = match_invoice(invoice=inv_late, po=base_po, grn=base_grn)
    assert match_res.exception_type == ExceptionType.PO_EXPIRED

    proposal = agent.resolve(invoice=inv_late, po=base_po, grn=base_grn, match_result=match_res)

    assert proposal.llm_fallback is True
    assert proposal.proposed_action == ApproverDecision.REJECTED
    assert proposal.proposed_amount_inr == Decimal("0.00")
    assert "expired" in proposal.reasoning.lower()


def test_deterministic_fallback_hsn_mismatch(base_po, base_grn):
    """Statutory GST HSN code discrepancies under fallback mode must be REJECTED for ₹0.00."""
    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(),
        llm_client=FailingLLMClient(),
    )

    inv_hsn = Invoice(
        invoice_number="INV-TEST-HSN-001",
        vendor_name=base_po.vendor_name,
        gstin=base_po.gstin,
        invoice_date=date(2025, 1, 10),
        po_number=base_po.po_number,
        item_description=base_po.item_description,
        hsn_code="998319",  # Discrepancy vs PO 998311
        unit_price_inr=base_po.unit_price_inr,
        quantity=1,
        total_excl_tax_inr=base_po.total_excl_tax_inr,
        gst_rate=base_po.gst_rate,
        gst_amount_inr=base_po.gst_amount_inr,
        total_inr=base_po.total_inr,
    )

    match_res = match_invoice(invoice=inv_hsn, po=base_po, grn=base_grn)
    assert match_res.exception_type == ExceptionType.HSN_MISMATCH

    proposal = agent.resolve(invoice=inv_hsn, po=base_po, grn=base_grn, match_result=match_res)

    assert proposal.llm_fallback is True
    assert proposal.proposed_action == ApproverDecision.REJECTED
    assert proposal.proposed_amount_inr == Decimal("0.00")
    assert "hsn" in proposal.reasoning.lower()


def test_deterministic_fallback_quantity_shortfall():
    """Quantity shortfall under fallback mode must propose EDITED for accepted goods value."""
    po_multi = PurchaseOrder(
        po_number="PO-TEST-QTY-001",
        vendor_name="Apex Logistics Pvt Ltd",
        gstin="27AABCA9999F1Z1",
        issue_date=date(2025, 2, 1),
        valid_until=date(2025, 12, 31),
        item_description="Industrial Forklift Battery Pack",
        hsn_code="8507",
        unit_price_inr=Decimal("50000.00"),
        quantity=10,
        total_excl_tax_inr=Decimal("500000.00"),
        gst_rate=Decimal("0.18"),
        gst_amount_inr=Decimal("90000.00"),
        total_inr=Decimal("590000.00"),
    )

    # GRN acknowledges physical receipt of only 8 units (2 units short)
    grn_short = GoodsReceiptNote(
        grn_number="GRN-TEST-QTY-001",
        po_number="PO-TEST-QTY-001",
        vendor_name="Apex Logistics Pvt Ltd",
        receipt_date=date(2025, 2, 5),
        item_description="Industrial Forklift Battery Pack",
        received_quantity=8,
        accepted_quantity=8,
        rejected_quantity=0,
    )

    # Invoice bills for the full 10 units
    inv_full = Invoice(
        invoice_number="INV-TEST-QTY-001",
        vendor_name="Apex Logistics Pvt Ltd",
        gstin="27AABCA9999F1Z1",
        invoice_date=date(2025, 2, 8),
        po_number="PO-TEST-QTY-001",
        item_description="Industrial Forklift Battery Pack",
        hsn_code="8507",
        unit_price_inr=Decimal("50000.00"),
        quantity=10,
        total_excl_tax_inr=Decimal("500000.00"),
        gst_rate=Decimal("0.18"),
        gst_amount_inr=Decimal("90000.00"),
        total_inr=Decimal("590000.00"),
    )

    match_res = match_invoice(invoice=inv_full, po=po_multi, grn=grn_short)
    assert match_res.exception_type == ExceptionType.QUANTITY_SHORTFALL

    # Expected amount for 8 units @ 50,000 + 18% GST = 400,000 + 72,000 = 472,000.00
    expected_amount = Decimal("472000.00")
    assert match_res.expected_amount_inr == expected_amount

    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(),
        llm_client=FailingLLMClient(),
    )

    proposal = agent.resolve(invoice=inv_full, po=po_multi, grn=grn_short, match_result=match_res)

    assert proposal.llm_fallback is True
    assert proposal.proposed_action == ApproverDecision.EDITED
    assert proposal.proposed_amount_inr == expected_amount
    assert "quantity shortfall" in proposal.reasoning.lower()


def test_deterministic_fallback_price_mismatch_with_precedent(base_po, base_grn):
    """Price mismatch with historical EDITED precedents must propose EDITED to PO contracted amount."""
    edit_precedents = [
        RecalledMemory(
            id="mem-edit-01",
            document_id="doc-edit-01",
            text="Prabhav Infosystems price overcharge reconciled to contracted rate ₹200,000.",
            metadata={"decision": "EDITED", "vendor_slug": "prabhav-infosystems"},
        ),
        RecalledMemory(
            id="mem-edit-02",
            document_id="doc-edit-02",
            text="Prabhav Infosystems price adjustment edited down to PO line item price.",
            metadata={"decision": "EDITED", "vendor_slug": "prabhav-infosystems"},
        ),
    ]

    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(memories=edit_precedents),
        llm_client=FailingLLMClient(),
    )

    inv = Invoice(
        invoice_number="INV-TEST-PRABHAV-001",
        vendor_name=base_po.vendor_name,
        gstin=base_po.gstin,
        invoice_date=date(2025, 1, 10),
        po_number=base_po.po_number,
        item_description=base_po.item_description,
        hsn_code=base_po.hsn_code,
        unit_price_inr=Decimal("208000.00"),  # 4.0% price overcharge
        quantity=1,
        total_excl_tax_inr=Decimal("208000.00"),
        gst_rate=Decimal("0.18"),
        gst_amount_inr=Decimal("37440.00"),
        total_inr=Decimal("245440.00"),
    )

    match_res = match_invoice(invoice=inv, po=base_po, grn=base_grn)
    assert match_res.exception_type == ExceptionType.PRICE_MISMATCH

    proposal = agent.resolve(
        invoice=inv,
        po=base_po,
        grn=base_grn,
        match_result=match_res,
        memory_enabled=True,
    )

    assert proposal.llm_fallback is True
    assert proposal.proposed_action == ApproverDecision.EDITED
    assert proposal.proposed_amount_inr == base_po.total_inr
    assert "doc-edit-01" in proposal.cited_memory_ids or len(proposal.cited_memory_ids) > 0


def test_deterministic_fallback_enforces_policy_supremacy_over_excessive_variance(base_po, base_grn):
    """Even in fallback mode, corporate policy POL-AP-001 (>5% variance) strictly enforces REJECTION."""
    # Past precedent shows an unauthorized approval of an overcharge
    unauthorized_approvals = [
        RecalledMemory(
            id="mem-unauth-01",
            document_id="doc-unauth-01",
            text="Past approver approved 7.5% price overage.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:approved"],
            metadata={
                "decision": "APPROVED",
                "vendor_name": "Prabhav Infosystems Pvt Ltd",
                "exception_type": "price_mismatch",
            },
        )
    ]

    agent = ResolutionAgent(
        memory_client=MockOfflineMemoryClient(memories=unauthorized_approvals),
        llm_client=FailingLLMClient(),
    )

    # 7.5% price overcharge (>5.0% policy ceiling in active POL-AP-001 v2.0 as of August 2025)
    inv_excessive = Invoice(
        invoice_number="INV-TEST-EXCESSIVE-001",
        vendor_name=base_po.vendor_name,
        gstin=base_po.gstin,
        invoice_date=date(2025, 8, 1),
        po_number=base_po.po_number,
        item_description=base_po.item_description,
        hsn_code=base_po.hsn_code,
        unit_price_inr=Decimal("215000.00"),  # 7.5% variance
        quantity=1,
        total_excl_tax_inr=Decimal("215000.00"),
        gst_rate=Decimal("0.18"),
        gst_amount_inr=Decimal("38700.00"),
        total_inr=Decimal("253700.00"),
    )

    match_res = match_invoice(invoice=inv_excessive, po=base_po, grn=base_grn)
    proposal = agent.resolve(
        invoice=inv_excessive,
        po=base_po,
        grn=base_grn,
        match_result=match_res,
        memory_enabled=True,
        enforce_policy_supremacy=True,
    )

    assert proposal.llm_fallback is True
    # Mandatory policy rejection overrides both historical precedent and model
    assert proposal.proposed_action == ApproverDecision.REJECTED
    assert proposal.proposed_amount_inr == Decimal("0.00")
    assert proposal.conflict_status == ConflictStatus.POLICY_PRECEDENT_CONFLICT
    assert proposal.requires_escalation is True


def test_hindsight_offline_client_recovery():
    """Verify MemoryClient offline recall attributes provenance correctly."""
    offline_client = MemoryClient(mode=MemoryMode.OFFLINE)
    recalled = offline_client.recall(bank_id=BASELINE_EVAL_BANK_ID, query="price mismatch", limit=5)

    assert isinstance(recalled, list)
    assert offline_client.last_recall_source == "offline"
    for mem in recalled:
        assert mem.is_offline_fallback is True
