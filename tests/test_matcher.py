"""
tests/test_matcher.py
────────────────────────────────────────────────────────────────────────────────
Unit tests for LedgerMind's deterministic Three-Way Matching engine (agent/matcher.py).
Tests all 6 exception types, clean matches, delta calculations, and priority ordering.
"""

from datetime import date, timedelta
from decimal import Decimal

from agent.matcher import match_invoice, EXCEPTION_PRIORITY
from data.models import ExceptionType, GoodsReceiptNote, Invoice, PurchaseOrder


def test_clean_three_way_match(sample_po, sample_grn, sample_clean_invoice, paid_invoice_registry):
    """A perfectly aligned invoice, PO, and GRN should match with 0 discrepancies."""
    res = match_invoice(
        invoice=sample_clean_invoice,
        po=sample_po,
        grn=sample_grn,
        paid_invoice_numbers=paid_invoice_registry,
    )
    assert res.is_match is True
    assert res.primary_discrepancy is None
    assert len(res.discrepancies) == 0
    assert "3-way match passed" in res.summary.lower()


def test_price_mismatch(sample_po, sample_grn, paid_invoice_registry):
    """Detects unit price higher than contracted PO rate."""
    higher_rate = Decimal("2100.00")  # PO is 2000.00
    inv = Invoice.create(
        invoice_number="INV-PM-001",
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=sample_po.issue_date + timedelta(days=10),
        po_number=sample_po.po_number,
        grn_number=sample_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code=sample_po.hsn_code,
        unit_price_inr=higher_rate,
        quantity=sample_po.quantity,
        gst_rate=sample_po.gst_rate,
    )
    res = match_invoice(invoice=inv, po=sample_po, grn=sample_grn, paid_invoice_numbers=paid_invoice_registry)

    assert res.is_match is False
    assert res.primary_discrepancy is not None
    assert res.primary_discrepancy.exception_type == ExceptionType.PRICE_MISMATCH
    assert res.primary_discrepancy.field == "unit_price_inr"
    # Unit diff = 100, qty = 100, subtotal diff = 10000, + 18% tax = 11800
    expected_delta = Decimal("11800.00")
    assert res.primary_discrepancy.delta_inr == expected_delta


def test_quantity_shortfall(sample_po, paid_invoice_registry):
    """Detects GRN accepted quantity being less than billed invoice quantity."""
    # GRN received 80 instead of 100
    shortfall_grn = GoodsReceiptNote(
        grn_number="GRN-SHORT-001",
        po_number=sample_po.po_number,
        receipt_date=sample_po.issue_date + timedelta(days=5),
        received_quantity=100,
        accepted_quantity=80,
        rejected_quantity=20,
        inspection_notes="20 units damaged in transit.",
    )
    inv = Invoice.create(
        invoice_number="INV-QS-001",
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=sample_po.issue_date + timedelta(days=10),
        po_number=sample_po.po_number,
        grn_number=shortfall_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code=sample_po.hsn_code,
        unit_price_inr=sample_po.unit_price_inr,
        quantity=100,  # Billed 100
        gst_rate=sample_po.gst_rate,
    )
    res = match_invoice(invoice=inv, po=sample_po, grn=shortfall_grn, paid_invoice_numbers=paid_invoice_registry)

    assert res.is_match is False
    assert res.primary_discrepancy is not None
    assert res.primary_discrepancy.exception_type == ExceptionType.QUANTITY_SHORTFALL
    assert res.primary_discrepancy.invoice_value == 100
    assert res.primary_discrepancy.expected_value == 80
    # Shortfall: 20 units * 2000 = 40000 subtotal, + 18% GST = 47200
    assert res.primary_discrepancy.delta_inr == Decimal("47200.00")


def test_duplicate_invoice(sample_po, sample_grn, paid_invoice_registry):
    """Detects resubmission of an invoice that already cleared payment."""
    dup_inv_no = "INV-ALREADY-PAID-001"
    inv = Invoice.create(
        invoice_number=dup_inv_no,
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=sample_po.issue_date + timedelta(days=10),
        po_number=sample_po.po_number,
        grn_number=sample_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code=sample_po.hsn_code,
        unit_price_inr=sample_po.unit_price_inr,
        quantity=sample_po.quantity,
        gst_rate=sample_po.gst_rate,
    )
    res = match_invoice(invoice=inv, po=sample_po, grn=sample_grn, paid_invoice_numbers=paid_invoice_registry)

    assert res.is_match is False
    assert res.primary_discrepancy is not None
    assert res.primary_discrepancy.exception_type == ExceptionType.DUPLICATE_INVOICE
    assert res.primary_discrepancy.field == "invoice_number"
    assert res.primary_discrepancy.delta_inr == inv.total_inr


def test_gst_rate_error(sample_po, sample_grn, paid_invoice_registry):
    """Detects incorrect statutory GST rate applied on invoice."""
    wrong_gst = Decimal("0.28")  # PO is 0.18
    inv = Invoice.create(
        invoice_number="INV-GST-001",
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=sample_po.issue_date + timedelta(days=10),
        po_number=sample_po.po_number,
        grn_number=sample_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code=sample_po.hsn_code,
        unit_price_inr=sample_po.unit_price_inr,
        quantity=sample_po.quantity,
        gst_rate=wrong_gst,
    )
    res = match_invoice(invoice=inv, po=sample_po, grn=sample_grn, paid_invoice_numbers=paid_invoice_registry)

    assert res.is_match is False
    assert res.primary_discrepancy is not None
    assert res.primary_discrepancy.exception_type == ExceptionType.GST_RATE_ERROR
    # Tax diff = (200000 * 0.28) - (200000 * 0.18) = 56000 - 36000 = 20000
    assert res.primary_discrepancy.delta_inr == Decimal("20000.00")


def test_po_expired(sample_po, sample_grn, paid_invoice_registry):
    """Detects invoice submitted after PO validity period has lapsed."""
    late_inv_date = sample_po.valid_until + timedelta(days=15)
    inv = Invoice.create(
        invoice_number="INV-EXP-001",
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=late_inv_date,
        po_number=sample_po.po_number,
        grn_number=sample_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code=sample_po.hsn_code,
        unit_price_inr=sample_po.unit_price_inr,
        quantity=sample_po.quantity,
        gst_rate=sample_po.gst_rate,
    )
    res = match_invoice(invoice=inv, po=sample_po, grn=sample_grn, paid_invoice_numbers=paid_invoice_registry)

    assert res.is_match is False
    assert res.primary_discrepancy is not None
    assert res.primary_discrepancy.exception_type == ExceptionType.PO_EXPIRED
    assert "15 days after validity expiry" in res.primary_discrepancy.message


def test_hsn_mismatch(sample_po, sample_grn, paid_invoice_registry):
    """Detects classification HSN code mismatch."""
    different_hsn = "998315"  # PO is 998314
    inv = Invoice.create(
        invoice_number="INV-HSN-001",
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=sample_po.issue_date + timedelta(days=10),
        po_number=sample_po.po_number,
        grn_number=sample_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code=different_hsn,
        unit_price_inr=sample_po.unit_price_inr,
        quantity=sample_po.quantity,
        gst_rate=sample_po.gst_rate,
    )
    res = match_invoice(invoice=inv, po=sample_po, grn=sample_grn, paid_invoice_numbers=paid_invoice_registry)

    assert res.is_match is False
    assert res.primary_discrepancy is not None
    assert res.primary_discrepancy.exception_type == ExceptionType.HSN_MISMATCH
    assert res.primary_discrepancy.invoice_value == different_hsn
    assert res.primary_discrepancy.expected_value == sample_po.hsn_code


def test_exception_priority_hierarchy(sample_po, sample_grn, paid_invoice_registry):
    """
    When multiple discrepancies are present, the matcher must rank them
    deterministically per EXCEPTION_PRIORITY:
      DUPLICATE > PO_EXPIRED > GST_RATE_ERROR > QUANTITY_SHORTFALL > PRICE_MISMATCH > HSN_MISMATCH
    """
    # Create invoice with:
    # 1. Duplicate invoice number
    # 2. Price mismatch
    # 3. HSN mismatch
    inv = Invoice.create(
        invoice_number="INV-ALREADY-PAID-001",  # DUPLICATE
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=sample_po.issue_date + timedelta(days=10),
        po_number=sample_po.po_number,
        grn_number=sample_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code="999999",                      # HSN MISMATCH
        unit_price_inr=Decimal("3000.00"),      # PRICE MISMATCH
        quantity=sample_po.quantity,
        gst_rate=sample_po.gst_rate,
    )
    res = match_invoice(invoice=inv, po=sample_po, grn=sample_grn, paid_invoice_numbers=paid_invoice_registry)

    assert res.is_match is False
    assert len(res.discrepancies) == 3
    # Highest priority is DUPLICATE_INVOICE
    assert res.primary_discrepancy.exception_type == ExceptionType.DUPLICATE_INVOICE

    # Now test PO_EXPIRED + PRICE_MISMATCH (PO_EXPIRED must take precedence)
    inv_expired = Invoice.create(
        invoice_number="INV-UNPAID-001",
        vendor_name=sample_po.vendor_name,
        gstin=sample_po.gstin,
        invoice_date=sample_po.valid_until + timedelta(days=10),  # PO_EXPIRED
        po_number=sample_po.po_number,
        grn_number=sample_grn.grn_number,
        item_description=sample_po.item_description,
        hsn_code=sample_po.hsn_code,
        unit_price_inr=Decimal("3000.00"),                        # PRICE_MISMATCH
        quantity=sample_po.quantity,
        gst_rate=sample_po.gst_rate,
    )
    res2 = match_invoice(invoice=inv_expired, po=sample_po, grn=sample_grn, paid_invoice_numbers=paid_invoice_registry)
    assert res2.primary_discrepancy.exception_type == ExceptionType.PO_EXPIRED

