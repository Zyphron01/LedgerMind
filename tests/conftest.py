"""
tests/conftest.py
────────────────────────────────────────────────────────────────────────────────
Shared fixtures and mock entities for LedgerMind test suite.
"""

from datetime import date, timedelta
from decimal import Decimal
import pytest
from typing import Set

from data.models import GoodsReceiptNote, Invoice, PurchaseOrder, Vendor
from data.vendors import VENDORS_BY_SLUG


@pytest.fixture
def sample_vendor() -> Vendor:
    """Fixture providing a standard fictional vendor."""
    return VENDORS_BY_SLUG["prabhav-infosystems"]


@pytest.fixture
def sample_po(sample_vendor: Vendor) -> PurchaseOrder:
    """Standard valid Purchase Order."""
    issue_d = date(2025, 3, 1)
    return PurchaseOrder.create(
        po_number="PO-TEST-001",
        vendor_name=sample_vendor.name,
        gstin=sample_vendor.gstin,
        issue_date=issue_d,
        valid_until=issue_d + timedelta(days=60),
        item_description="Cloud Engineering Consulting",
        hsn_code=sample_vendor.standard_hsn,
        unit_price_inr=Decimal("2000.00"),
        quantity=100,
        gst_rate=sample_vendor.standard_gst_rate,
    )


@pytest.fixture
def sample_grn(sample_po: PurchaseOrder) -> GoodsReceiptNote:
    """Matching Goods Receipt Note with 100% accepted quantity."""
    return GoodsReceiptNote(
        grn_number="GRN-TEST-001",
        po_number=sample_po.po_number,
        receipt_date=sample_po.issue_date + timedelta(days=5),
        received_quantity=sample_po.quantity,
        accepted_quantity=sample_po.quantity,
        rejected_quantity=0,
        inspection_notes="Received and verified in full.",
    )


@pytest.fixture
def sample_clean_invoice(sample_po: PurchaseOrder, sample_grn: GoodsReceiptNote) -> Invoice:
    """Matching Invoice with zero discrepancy against PO and GRN."""
    return Invoice.create(
        invoice_number="INV-TEST-001",
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


@pytest.fixture
def paid_invoice_registry() -> Set[str]:
    """Pre-populated set of previously paid invoice numbers."""
    return {"INV-ALREADY-PAID-001", "INV-ALREADY-PAID-002"}

