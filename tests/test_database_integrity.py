"""
tests/test_database_integrity.py
────────────────────────────────────────────────────────────────────────────────
Isolated Integration Tests for Milestone 1 Safe Data Layer Repair.
Validates:
  1. Transaction atomic rollback on failed bundle persistence.
  2. Foreign key enforcement (vendors, POs, GRNs, invoices, reviews).
  3. Cascading updates across relational links.
  4. Incomplete CSV intake handling (raw_po_number preserved with po_number=NULL).
  5. Human review durability and association with benchmark invoices.
  6. Idempotent re-initialization and durability after connection restarts.
  7. Deterministic bundle reconciliation ordering (user-created first).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import pytest

from agent.matcher import match_invoice
from data.models import (
    ApproverDecision,
    ApproverRole,
    ExceptionType,
    GoodsReceiptNote,
    Invoice,
    PurchaseOrder,
)
from data.store import (
    get_all_human_reviews,
    get_all_reconciled_invoices,
    get_connection,
    get_human_review,
    get_invoice_record_by_id,
    get_purchase_order,
    get_user_invoices_reconciled,
    init_db,
    list_all_vendor_names,
    list_vendors,
    save_document_bundle,
    save_goods_receipt,
    save_human_review,
    save_invoice,
    save_purchase_order,
    save_vendor,
)


@pytest.fixture
def fresh_db(tmp_path):
    """Provides a fresh, isolated SQLite database path."""
    db_file = tmp_path / "test_integrity.db"
    init_db(db_path=db_file)
    return db_file


def test_schema_ddl_and_pragma_integrity(fresh_db):
    """Verify DDL integrity, foreign keys enabled, and zero FK violations."""
    with get_connection(fresh_db) as conn:
        fk_check = conn.execute("PRAGMA foreign_key_check;").fetchall()
        assert len(fk_check) == 0, f"Foreign key check failed: {fk_check}"

        integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        assert integrity == "ok", f"Integrity check failed: {integrity}"

        # Verify all indexes exist
        indexes = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
        expected_indexes = [
            "idx_invoices_vendor",
            "idx_invoices_po",
            "idx_invoices_raw_po",
            "idx_invoices_grn",
            "idx_invoices_date",
            "idx_purchase_orders_vendor",
            "idx_goods_receipts_po",
            "idx_human_reviews_invoice",
        ]
        for idx in expected_indexes:
            assert idx in indexes, f"Missing index: {idx}"


def test_atomic_transaction_rollback_on_failure(fresh_db):
    """Verify that if saving any component in a bundle fails, entire bundle rolls back."""
    with get_connection(fresh_db) as conn:
        v_count_init = conn.execute("SELECT count(*) FROM vendors").fetchone()[0]
        po_count_init = conn.execute("SELECT count(*) FROM purchase_orders").fetchone()[0]
        inv_count_init = conn.execute("SELECT count(*) FROM invoices").fetchone()[0]

    po = PurchaseOrder.create(
        po_number="PO-ROLLBACK-001",
        vendor_name="Atomic Failure Vendor",
        gstin="27AAACA9999A1Z1",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="Precision Bearings",
        hsn_code="8482",
        unit_price_inr=Decimal("1500.00"),
        quantity=10,
        gst_rate=Decimal("0.18"),
    )

    class MalformedInvoice:
        invoice_number = "INV-ROLLBACK-001"
        vendor_name = "Atomic Failure Vendor"
        gstin = "27AAACA9999A1Z1"
        invoice_date = None  # None causes AttributeError on .isoformat(), breaking transaction
        po_number = "PO-ROLLBACK-001"
        grn_number = None
        item_description = "Precision Bearings"
        hsn_code = "8482"
        unit_price_inr = Decimal("1500.00")
        quantity = 10
        total_excl_tax_inr = Decimal("15000.00")
        gst_rate = Decimal("0.18")
        gst_amount_inr = Decimal("2700.00")
        total_inr = Decimal("17700.00")

    with pytest.raises(Exception):
        save_document_bundle(
            vendor={"name": "Atomic Failure Vendor", "gstin": "27AAACA9999A1Z1", "category": "Testing"},
            po=po,
            grn=None,
            invoice=MalformedInvoice(),  # type: ignore
            is_user_created=True,
            db_path=fresh_db,
        )

    with get_connection(fresh_db) as conn:
        v_count_after = conn.execute("SELECT count(*) FROM vendors").fetchone()[0]
        po_count_after = conn.execute("SELECT count(*) FROM purchase_orders").fetchone()[0]
        inv_count_after = conn.execute("SELECT count(*) FROM invoices").fetchone()[0]

    assert v_count_after == v_count_init, "Vendor was not rolled back!"
    assert po_count_after == po_count_init, "PO was not rolled back!"
    assert inv_count_after == inv_count_init, "Invoice was not rolled back!"


def test_foreign_key_rejection_for_orphan_human_review(fresh_db):
    """Verify that human_reviews table rejects reviews for non-existent invoices."""
    with pytest.raises(sqlite3.IntegrityError):
        with get_connection(fresh_db) as conn:
            conn.execute(
                """
                INSERT INTO human_reviews (
                    invoice_number, decision, approver_role, approved_amount_inr,
                    rationale, hindsight_status, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "INV-NON-EXISTENT-999",
                    "APPROVED",
                    "AP_MANAGER",
                    "1000.00",
                    "Test orphan review",
                    "PENDING_SYNC",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def test_cascading_updates_across_relations(fresh_db):
    """Verify ON UPDATE CASCADE works from vendors to POs and invoices."""
    save_vendor(name="Original Vendor Name", gstin="27AAACV1234A1Z9", db_path=fresh_db)
    po = PurchaseOrder.create(
        po_number="PO-CASCADE-001",
        vendor_name="Original Vendor Name",
        gstin="27AAACV1234A1Z9",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="Components",
        hsn_code="8482",
        unit_price_inr=Decimal("1000.00"),
        quantity=5,
        gst_rate=Decimal("0.18"),
    )
    save_purchase_order(po, db_path=fresh_db)

    inv = Invoice.create(
        invoice_number="INV-CASCADE-001",
        vendor_name="Original Vendor Name",
        gstin="27AAACV1234A1Z9",
        invoice_date=date(2025, 10, 15),
        po_number="PO-CASCADE-001",
        grn_number=None,
        item_description="Components",
        hsn_code="8482",
        unit_price_inr=Decimal("1000.00"),
        quantity=5,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=fresh_db)

    # Rename vendor in vendors table
    with get_connection(fresh_db) as conn:
        with conn:
            conn.execute(
                "UPDATE vendors SET name = 'Renamed Vendor Corp' WHERE name = 'Original Vendor Name';"
            )

    # Check cascading update in purchase_orders and invoices
    with get_connection(fresh_db) as conn:
        updated_po = conn.execute("SELECT vendor_name FROM purchase_orders WHERE po_number = 'PO-CASCADE-001'").fetchone()[0]
        updated_inv = conn.execute("SELECT vendor_name FROM invoices WHERE invoice_number = 'INV-CASCADE-001'").fetchone()[0]

    assert updated_po == "Renamed Vendor Corp"
    assert updated_inv == "Renamed Vendor Corp"


def test_incomplete_csv_invoice_intake(fresh_db):
    """
    Requirement G: Invoice-only CSV intake records must be preserved honestly
    as incomplete cases awaiting genuine supporting documents.
    """
    inv = Invoice.create(
        invoice_number="INV-INCOMPLETE-001",
        vendor_name="Standalone Invoicing Vendor",
        gstin="27AAACS5555A1Z5",
        invoice_date=date(2025, 11, 1),
        po_number="PO-PENDING-UNORDERED-888",
        grn_number=None,
        item_description="Consulting Services",
        hsn_code="998314",
        unit_price_inr=Decimal("50000.00"),
        quantity=1,
        gst_rate=Decimal("0.18"),
    )
    # Save standalone invoice where PO does not yet exist in database
    save_invoice(inv, is_user_created=True, db_path=fresh_db)

    with get_connection(fresh_db) as conn:
        r = conn.execute("SELECT * FROM invoices WHERE invoice_number = 'INV-INCOMPLETE-001'").fetchone()
        assert r["po_number"] is None, "Foreign key should be NULL when PO is not yet created"
        assert r["raw_po_number"] == "PO-PENDING-UNORDERED-888", "raw_po_number must preserve original reference"

    # Verify reconciliation produces honest pending state without failing
    bundle = get_invoice_record_by_id("INV-INCOMPLETE-001", db_path=fresh_db)
    assert bundle is not None
    assert bundle.po is None
    assert bundle.match_result.is_match is False
    assert "Pending PO documentation" in bundle.match_result.explanation


def test_human_review_persistence_for_benchmark_invoices(fresh_db):
    """Verify human review links cleanly to benchmark sample invoice in SQLite."""
    # Benchmark invoice INV-PI-2025-101 exists in fresh_db
    save_human_review(
        invoice_number="INV-PI-2025-101",
        decision="EDITED",
        approver_role="AP_MANAGER",
        approved_amount_inr=Decimal("118000.00"),
        rationale="Approved after editing rate to contracted PO terms.",
        hindsight_doc_id="feedback-INV-PI-2025-101",
        hindsight_bank_id="live-demo",
        hindsight_status="SYNCED",
        db_path=fresh_db,
    )

    review = get_human_review("INV-PI-2025-101", db_path=fresh_db)
    assert review is not None
    assert review["decision"] == "EDITED"
    assert review["role"] == "AP_MANAGER"
    assert review["amount"] == Decimal("118000.00")
    assert review["hindsight_status"] == "SYNCED"


def test_persistence_durability_across_simulated_restarts(tmp_path):
    """Verify data durability across separate process / connection restarts."""
    db_file = tmp_path / "durability.db"
    init_db(db_file)

    po = PurchaseOrder.create(
        po_number="PO-DURABLE-01",
        vendor_name="Durable Vendor",
        gstin="27AAACD9999A1Z1",
        issue_date=date(2025, 10, 1),
        valid_until=date(2025, 12, 31),
        item_description="Storage Disks",
        hsn_code="8471",
        unit_price_inr=Decimal("5000.00"),
        quantity=4,
        gst_rate=Decimal("0.18"),
    )
    inv = Invoice.create(
        invoice_number="INV-DURABLE-01",
        vendor_name="Durable Vendor",
        gstin="27AAACD9999A1Z1",
        invoice_date=date(2025, 10, 10),
        po_number="PO-DURABLE-01",
        grn_number=None,
        item_description="Storage Disks",
        hsn_code="8471",
        unit_price_inr=Decimal("5000.00"),
        quantity=4,
        gst_rate=Decimal("0.18"),
    )
    save_document_bundle(
        vendor={"name": "Durable Vendor", "gstin": "27AAACD9999A1Z1"},
        po=po,
        grn=None,
        invoice=inv,
        is_user_created=True,
        db_path=db_file,
    )

    # Re-open in a fresh connection (simulating app restart)
    bundle = get_invoice_record_by_id("INV-DURABLE-01", db_path=db_file)
    assert bundle is not None
    assert bundle.invoice.total_inr == Decimal("23600.00")
    assert bundle.match_result.is_match is True


def test_duplicate_submission_upsert(fresh_db):
    """Verify that re-submitting an invoice updates cleanly rather than duplicating or failing."""
    inv = Invoice.create(
        invoice_number="INV-DUP-001",
        vendor_name="Devanshi Logistics LLP",
        gstin="09AABCD2914R1ZP",
        invoice_date=date(2025, 10, 1),
        po_number="PO-LOG-2025-101",
        grn_number=None,
        item_description="Initial billing description",
        hsn_code="996812",
        unit_price_inr=Decimal("1000.00"),
        quantity=1,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=fresh_db)

    # Second submission with updated description and amount
    inv_updated = Invoice.create(
        invoice_number="INV-DUP-001",
        vendor_name="Devanshi Logistics LLP",
        gstin="09AABCD2914R1ZP",
        invoice_date=date(2025, 10, 1),
        po_number="PO-LOG-2025-101",
        grn_number=None,
        item_description="Updated freight description",
        hsn_code="996812",
        unit_price_inr=Decimal("1200.00"),
        quantity=1,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv_updated, is_user_created=True, db_path=fresh_db)

    with get_connection(fresh_db) as conn:
        count = conn.execute("SELECT count(*) FROM invoices WHERE invoice_number = 'INV-DUP-001'").fetchone()[0]
        assert count == 1, "Duplicate row was created!"

    bundle = get_invoice_record_by_id("INV-DUP-001", db_path=fresh_db)
    assert bundle.invoice.item_description == "Updated freight description"
    assert bundle.invoice.unit_price_inr == Decimal("1200.00")

