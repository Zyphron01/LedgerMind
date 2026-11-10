"""
tests/test_document_intake_persistence.py
────────────────────────────────────────────────────────────────────────────────
End-to-end unit and integration tests for real document intake, SQLite persistence,
deterministic matching, and human review persistence.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import pytest

from agent.matcher import match_invoice
from agent.resolver import ResolutionAgent
from data.models import ApproverDecision, ApproverRole, ExceptionType, GoodsReceiptNote, Invoice, PurchaseOrder
from data.store import (
    get_all_human_reviews,
    get_goods_receipt,
    get_human_review,
    get_purchase_order,
    get_user_invoices_reconciled,
    init_db,
    list_purchase_orders,
    list_vendors,
    save_goods_receipt,
    save_human_review,
    save_invoice,
    save_purchase_order,
    save_vendor,
)
from memory.client import MemoryClient


@pytest.fixture
def temp_db(tmp_path):
    """Fixture providing a temporary SQLite database path."""
    db_file = tmp_path / "test_intake.db"
    init_db(db_path=db_file)
    return db_file


def test_sqlite_vendor_and_po_persistence(temp_db):
    """Test saving and retrieving vendors and purchase orders."""
    save_vendor(
        name="Zenith Industrial Components",
        gstin="27AAACZ1111A1Z2",
        category="Machinery Parts",
        db_path=temp_db,
    )
    vendors = list_vendors(db_path=temp_db)
    assert any(v["name"] == "Zenith Industrial Components" for v in vendors)

    po = PurchaseOrder.create(
        po_number="PO-TEST-100",
        vendor_name="Zenith Industrial Components",
        gstin="27AAACZ1111A1Z2",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="High-Speed Ball Bearings",
        hsn_code="8482",
        unit_price_inr=Decimal("1000.00"),
        quantity=10,
        gst_rate=Decimal("0.18"),
    )
    save_purchase_order(po, db_path=temp_db)

    retrieved_po = get_purchase_order("PO-TEST-100", db_path=temp_db)
    assert retrieved_po is not None
    assert retrieved_po.po_number == "PO-TEST-100"
    assert retrieved_po.quantity == 10
    assert retrieved_po.unit_price_inr == Decimal("1000.00")
    assert retrieved_po.total_inr == Decimal("11800.00")


def test_match_eight_percent_price_mismatch(temp_db):
    """
    Test user example:
    PO for 10 units at ₹1,000 each.
    GRN showing 10 units received.
    Supplier invoice billing ₹1,080 per unit (+8.0% variance).
    """
    po = PurchaseOrder.create(
        po_number="PO-TEST-008",
        vendor_name="Zenith Industrial Components",
        gstin="27AAACZ1111A1Z2",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="Precision Bearings",
        hsn_code="8482",
        unit_price_inr=Decimal("1000.00"),
        quantity=10,
        gst_rate=Decimal("0.18"),
    )
    save_purchase_order(po, db_path=temp_db)

    grn = GoodsReceiptNote(
        grn_number="GRN-TEST-008",
        po_number="PO-TEST-008",
        receipt_date=date(2025, 10, 5),
        received_quantity=10,
        accepted_quantity=10,
        rejected_quantity=0,
        inspection_notes="Delivery complete.",
    )
    save_goods_receipt(grn, db_path=temp_db)

    inv = Invoice.create(
        invoice_number="INV-TEST-008",
        vendor_name="Zenith Industrial Components",
        gstin="27AAACZ1111A1Z2",
        invoice_date=date(2025, 10, 10),
        po_number="PO-TEST-008",
        grn_number="GRN-TEST-008",
        item_description="Precision Bearings",
        hsn_code="8482",
        unit_price_inr=Decimal("1080.00"),
        quantity=10,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=temp_db)

    # Reconciled list
    user_invs = get_user_invoices_reconciled(db_path=temp_db)
    assert len(user_invs) == 1
    match = user_invs[0].match_result

    assert match.is_match is False
    assert match.exception_type == ExceptionType.PRICE_MISMATCH
    assert any(d.field == "unit_price_inr" for d in match.discrepancies)


def test_clean_match_invoice(temp_db):
    """Test invoice where all quantities, rates, and HSN codes match perfectly."""
    po = PurchaseOrder.create(
        po_number="PO-CLEAN-01",
        vendor_name="Alpha Tech",
        gstin="27AAACA1234A1Z1",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="Monitor 27 inch",
        hsn_code="8471",
        unit_price_inr=Decimal("15000.00"),
        quantity=2,
        gst_rate=Decimal("0.18"),
    )
    save_purchase_order(po, db_path=temp_db)

    grn = GoodsReceiptNote(
        grn_number="GRN-CLEAN-01",
        po_number="PO-CLEAN-01",
        receipt_date=date(2025, 10, 5),
        received_quantity=2,
        accepted_quantity=2,
        rejected_quantity=0,
        inspection_notes="Inspected and verified.",
    )
    save_goods_receipt(grn, db_path=temp_db)

    inv = Invoice.create(
        invoice_number="INV-CLEAN-01",
        vendor_name="Alpha Tech",
        gstin="27AAACA1234A1Z1",
        invoice_date=date(2025, 10, 10),
        po_number="PO-CLEAN-01",
        grn_number="GRN-CLEAN-01",
        item_description="Monitor 27 inch",
        hsn_code="8471",
        unit_price_inr=Decimal("15000.00"),
        quantity=2,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=temp_db)

    user_invs = get_user_invoices_reconciled(db_path=temp_db)
    assert len(user_invs) == 1
    assert user_invs[0].match_result.is_match is True


def test_human_review_persistence(temp_db):
    """Test recording and reloading a human review in SQLite."""
    inv = Invoice.create(
        invoice_number="INV-TEST-008",
        vendor_name="Zenith Industrial Components",
        gstin="27AAACZ1111A1Z2",
        invoice_date=date(2025, 10, 10),
        po_number="PO-TEST-008",
        grn_number=None,
        item_description="Precision Bearings",
        hsn_code="8482",
        unit_price_inr=Decimal("1080.00"),
        quantity=10,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=temp_db)

    save_human_review(
        invoice_number="INV-TEST-008",
        decision="ESCALATED",
        approver_role="FINANCE_CONTROLLER",
        approved_amount_inr=Decimal("12744.00"),
        rationale="Overcharge exceeds 1.0% tolerance ceiling; supplier dispute initiated.",
        hindsight_doc_id="feedback-INV-TEST-008",
        hindsight_bank_id="ledgermind-live-demo",
        hindsight_status="CONFIRMED_IN_HINDSIGHT",
        db_path=temp_db,
    )

    review = get_human_review("INV-TEST-008", db_path=temp_db)
    assert review is not None
    assert review["decision"] == "ESCALATED"
    assert review["role"] == "FINANCE_CONTROLLER"
    assert review["amount"] == Decimal("12744.00")
    assert review["hindsight_status"] == "CONFIRMED_IN_HINDSIGHT"


def test_gst_map_scope_and_existing_po_intake(temp_db):
    """
    Regression test for:
    UnboundLocalError: cannot access local variable 'gst_map' where it is not associated with a value
    Context:
    - Existing vendor: Nova Tech Supplies
    - Existing purchase order: PO-NOVA-001
    - Invoice quantity: 10
    - Billed unit price: 1100
    - Invoice GST selection: 18%
    """
    from ui.pages.intake import GST_RATE_MAP

    # 1. Verify GST_RATE_MAP has all statutory GST tiers with accurate decimal rates
    assert "18% (Standard Goods)" in GST_RATE_MAP
    assert "12% (Concessional)" in GST_RATE_MAP
    assert "5% (Essential)" in GST_RATE_MAP
    assert "28% (Luxury)" in GST_RATE_MAP
    assert "0% (Nil)" in GST_RATE_MAP
    assert GST_RATE_MAP["18% (Standard Goods)"] == 0.18
    assert GST_RATE_MAP["12% (Concessional)"] == 0.12
    assert GST_RATE_MAP["5% (Essential)"] == 0.05
    assert GST_RATE_MAP["28% (Luxury)"] == 0.28
    assert GST_RATE_MAP["0% (Nil)"] == 0.0

    # 2. Setup existing vendor & existing PO
    save_vendor(
        name="Nova Tech Supplies",
        gstin="27AABCN9999M1Z3",
        category="Hardware Components",
        db_path=temp_db,
    )
    existing_po = PurchaseOrder.create(
        po_number="PO-NOVA-001",
        vendor_name="Nova Tech Supplies",
        gstin="27AABCN9999M1Z3",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="Server Rack Cabinets",
        hsn_code="8471",
        unit_price_inr=Decimal("1000.00"),
        quantity=10,
        gst_rate=Decimal("0.18"),
    )
    save_purchase_order(existing_po, db_path=temp_db)

    # 3. Simulate existing PO retrieval path (is_new_po = False)
    all_pos = list_purchase_orders(db_path=temp_db)
    selected_po = next((p for p in all_pos if p.po_number == "PO-NOVA-001"), None)
    assert selected_po is not None

    # Verify that in this branch, GST map lookup succeeds for invoice without UnboundLocalError
    inv_gst_choice = "18% (Standard Goods)"
    inv_gst_rate_val = GST_RATE_MAP[inv_gst_choice]
    assert inv_gst_rate_val == 0.18

    # Create new invoice linked to existing PO
    billed_qty = 10
    billed_price = Decimal("1100.00")
    inv_sub = billed_price * billed_qty
    inv_tax = (inv_sub * Decimal(str(inv_gst_rate_val))).quantize(Decimal("0.01"))
    inv_tot = inv_sub + inv_tax

    inv = Invoice.create(
        invoice_number="INV-NOVA-2025-002",
        vendor_name="Nova Tech Supplies",
        gstin="27AABCN9999M1Z3",
        invoice_date=date(2025, 10, 20),
        po_number="PO-NOVA-001",
        grn_number=None,
        item_description="Server Rack Cabinets",
        hsn_code="8471",
        unit_price_inr=billed_price,
        quantity=billed_qty,
        gst_rate=Decimal(str(inv_gst_rate_val)),
    )
    save_invoice(inv, is_user_created=True, db_path=temp_db)

    # Verify match result detects 10% price mismatch
    match_res = match_invoice(invoice=inv, po=selected_po, grn=None)
    assert match_res.is_match is False
    assert match_res.exception_type == ExceptionType.PRICE_MISMATCH
    assert match_res.variance_inr == Decimal("1180.00")


def test_clean_match_resolution_proposal_no_name_error():
    """
    Regression test for:
    NameError: name 'ConfidenceBand' is not defined in clean-match proposal generation.
    """
    from agent.confidence import ConfidenceBand

    po = PurchaseOrder.create(
        po_number="PO-EXACT-01",
        vendor_name="Acme Precision",
        gstin="27AAACA0000A1Z0",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="Linear Bearings",
        hsn_code="8482",
        unit_price_inr=Decimal("500.00"),
        quantity=20,
        gst_rate=Decimal("0.18"),
    )
    grn = GoodsReceiptNote(
        grn_number="GRN-EXACT-01",
        po_number="PO-EXACT-01",
        receipt_date=date(2025, 10, 5),
        received_quantity=20,
        accepted_quantity=20,
        rejected_quantity=0,
        inspection_notes="Full delivery accepted.",
    )
    inv = Invoice.create(
        invoice_number="INV-EXACT-01",
        vendor_name="Acme Precision",
        gstin="27AAACA0000A1Z0",
        invoice_date=date(2025, 10, 10),
        po_number="PO-EXACT-01",
        grn_number="GRN-EXACT-01",
        item_description="Linear Bearings",
        hsn_code="8482",
        unit_price_inr=Decimal("500.00"),
        quantity=20,
        gst_rate=Decimal("0.18"),
    )

    match_res = match_invoice(invoice=inv, po=po, grn=grn)
    assert match_res.is_match is True

    agent = ResolutionAgent(memory_client=MemoryClient())
    proposal = agent.resolve(
        invoice=inv,
        po=po,
        grn=grn,
        match_result=match_res,
        memory_enabled=True,
    )

    assert proposal.proposed_action == ApproverDecision.APPROVED
    assert proposal.proposed_amount_inr == inv.total_inr
    assert proposal.confidence.band == ConfidenceBand.HIGH
    assert proposal.confidence.score == 1.0
    assert proposal.policy_id == "POL-AP-001"
    assert proposal.requires_escalation is False
