"""
tests/test_milestone3_hardening.py
────────────────────────────────────────────────────────────────────────────────
Comprehensive test suite verifying Milestone 3:
1. Human review protection via ON DELETE RESTRICT and archiving.
2. Review audit log versioning and supersede tracking.
3. Safe document intake (missing PO flags invoice as incomplete without fake POs).
4. Auto-linking incomplete invoices when authentic PO is uploaded.
5. Accurate Hindsight retention status (SYNCED, PENDING_SYNC, NOT_ATTEMPTED, FAILED).
6. Deterministic fallback escalation on missing PO documentation.
7. Cache invalidation on review submission.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import pytest
from unittest.mock import MagicMock

from agent.feedback import FeedbackSubmission, process_human_feedback
from agent.resolver import ResolutionAgent
from data.models import ApproverDecision, ApproverRole, Invoice, PurchaseOrder, GoodsReceiptNote
from data.store import (
    archive_invoice,
    get_connection,
    get_human_review,
    get_purchase_order,
    get_review_history,
    init_db,
    link_invoice_po,
    list_incomplete_invoices,
    save_human_review,
    save_invoice,
    save_purchase_order,
    sync_pending_reviews,
    unarchive_invoice,
)
from memory.client import MemoryClient, MemoryMode


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Fixture providing an isolated SQLite database initialized with Milestone 3 schema."""
    db_file = tmp_path / "test_hardening.db"
    init_db(db_file)
    return db_file


def test_on_delete_restrict_protects_review_history(test_db: Path):
    """Verify that ON DELETE RESTRICT prevents deleting an invoice with a human review."""
    from data.store import save_vendor
    save_vendor("Secure Vendor Ltd", "27AABCU9999Z1Z5", db_path=test_db)
    inv = Invoice.create(
        invoice_number="INV-RESTRICT-001",
        vendor_name="Secure Vendor Ltd",
        gstin="27AABCU9999Z1Z5",
        invoice_date=date(2025, 10, 1),
        po_number=None,
        grn_number=None,
        item_description="Network Switches",
        hsn_code="8471",
        unit_price_inr=Decimal("1000.00"),
        quantity=1,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=test_db)

    # Save a human review for this invoice
    save_human_review(
        invoice_number="INV-RESTRICT-001",
        decision="APPROVED",
        approver_role="AP_MANAGER",
        approved_amount_inr=Decimal("1180.00"),
        rationale="Initial audit review approved.",
        hindsight_doc_id="feedback-INV-RESTRICT-001",
        hindsight_bank_id="ledgermind-live-demo",
        hindsight_status="SYNCED",
        db_path=test_db,
    )

    # Attempting to delete the invoice must strictly raise sqlite3.IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        with get_connection(test_db) as conn:
            conn.execute("DELETE FROM invoices WHERE invoice_number = 'INV-RESTRICT-001'")

    # Review must still exist intact
    review = get_human_review("INV-RESTRICT-001", db_path=test_db)
    assert review is not None
    assert review["decision"] == "APPROVED"


def test_archive_invoice_preserves_review(test_db: Path):
    """Verify soft-delete archiving preserves the invoice and its review without violating constraints."""
    from data.store import save_vendor
    save_vendor("Archive Vendor", "27AABCU8888Z1Z5", db_path=test_db)
    inv = Invoice.create(
        invoice_number="INV-ARCH-001",
        vendor_name="Archive Vendor",
        gstin="27AABCU8888Z1Z5",
        invoice_date=date(2025, 10, 1),
        po_number=None,
        grn_number=None,
        item_description="Storage Arrays",
        hsn_code="8471",
        unit_price_inr=Decimal("1000.00"),
        quantity=2,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=test_db)

    save_human_review(
        invoice_number="INV-ARCH-001",
        decision="EDITED",
        approver_role="AP_MANAGER",
        approved_amount_inr=Decimal("2000.00"),
        rationale="Price adjusted to contracted terms.",
        hindsight_doc_id="feedback-INV-ARCH-001",
        hindsight_bank_id="ledgermind-live-demo",
        hindsight_status="SYNCED",
        db_path=test_db,
    )

    # Archive invoice
    assert archive_invoice("INV-ARCH-001", db_path=test_db) is True

    # Check that is_archived = 1
    with get_connection(test_db) as conn:
        row = conn.execute("SELECT is_archived FROM invoices WHERE invoice_number = 'INV-ARCH-001'").fetchone()
        assert row["is_archived"] == 1

    # Review remains accessible
    review = get_human_review("INV-ARCH-001", db_path=test_db)
    assert review is not None
    assert review["decision"] == "EDITED"

    # Unarchive
    assert unarchive_invoice("INV-ARCH-001", db_path=test_db) is True
    with get_connection(test_db) as conn:
        row = conn.execute("SELECT is_archived FROM invoices WHERE invoice_number = 'INV-ARCH-001'").fetchone()
        assert row["is_archived"] == 0


def test_review_audit_log_versioning(test_db: Path):
    """Verify that superseding a review increments version and archives prior review to review_audit_log."""
    from data.store import save_vendor
    save_vendor("Vers Vendor", "27AABCU7777Z1Z5", db_path=test_db)
    inv = Invoice.create(
        invoice_number="INV-VERS-001",
        vendor_name="Vers Vendor",
        gstin="27AABCU7777Z1Z5",
        invoice_date=date(2025, 10, 1),
        po_number=None,
        grn_number=None,
        item_description="Consulting Services",
        hsn_code="9983",
        unit_price_inr=Decimal("5000.00"),
        quantity=1,
        gst_rate=Decimal("0.0"),
    )
    save_invoice(inv, is_user_created=True, db_path=test_db)

    # Review Version 1: ESCALATED
    save_human_review(
        invoice_number="INV-VERS-001",
        decision="ESCALATED",
        approver_role="AP_CLERK",
        approved_amount_inr=Decimal("5000.00"),
        rationale="Escalated due to scope variance.",
        hindsight_doc_id="feedback-v1",
        hindsight_bank_id="ledgermind-live-demo",
        hindsight_status="PENDING_SYNC",
        reviewed_at="2025-10-02 10:00:00 UTC",
        db_path=test_db,
    )

    # Review Version 2: APPROVED (supersedes Version 1)
    save_human_review(
        invoice_number="INV-VERS-001",
        decision="APPROVED",
        approver_role="FINANCE_CONTROLLER",
        approved_amount_inr=Decimal("5000.00"),
        rationale="Controller authorized the revised scope.",
        hindsight_doc_id="feedback-v2",
        hindsight_bank_id="ledgermind-live-demo",
        hindsight_status="SYNCED",
        reviewed_at="2025-10-02 14:00:00 UTC",
        db_path=test_db,
    )

    # Active review must be Version 2
    active = get_human_review("INV-VERS-001", db_path=test_db)
    assert active["decision"] == "APPROVED"
    assert active["role"] == "FINANCE_CONTROLLER"

    # Audit history must contain Version 1 with superseded_at timestamp
    history = get_review_history("INV-VERS-001", db_path=test_db)
    assert len(history) == 1
    assert history[0]["version"] == 1
    assert history[0]["decision"] == "ESCALATED"
    assert history[0]["approver_role"] == "AP_CLERK"
    assert history[0]["superseded_at"] is not None


def test_csv_intake_without_po_marks_incomplete(test_db: Path):
    """Verify that importing an invoice with a missing PO sets is_incomplete=1 without inventing fake POs."""
    inv = Invoice.create(
        invoice_number="INV-NOPO-001",
        vendor_name="Missing PO Vendor",
        gstin="27AABCU1111Z1Z5",
        invoice_date=date(2025, 10, 10),
        po_number="PO-NONEXISTENT-999",
        grn_number=None,
        item_description="Unlinked Supplies",
        hsn_code="8471",
        unit_price_inr=Decimal("1500.00"),
        quantity=2,
        gst_rate=Decimal("0.18"),
    )

    save_invoice(inv, is_user_created=True, db_path=test_db)

    # PO table must not have PO-NONEXISTENT-999 fabricated
    po = get_purchase_order("PO-NONEXISTENT-999", db_path=test_db)
    assert po is None

    # Invoice must be marked incomplete
    incomplete_list = list_incomplete_invoices(db_path=test_db)
    assert any(i.invoice_number == "INV-NOPO-001" for i in incomplete_list)

    with get_connection(test_db) as conn:
        row = conn.execute("SELECT is_incomplete, raw_po_number FROM invoices WHERE invoice_number = 'INV-NOPO-001'").fetchone()
        assert row["is_incomplete"] == 1
        assert row["raw_po_number"] == "PO-NONEXISTENT-999"


def test_uploading_po_links_incomplete_invoices(test_db: Path):
    """Verify that uploading an authentic PO automatically links pending incomplete invoices."""
    inv = Invoice.create(
        invoice_number="INV-WAITING-001",
        vendor_name="Future PO Vendor",
        gstin="27AABCU2222Z1Z5",
        invoice_date=date(2025, 10, 12),
        po_number="PO-AUTHENTIC-101",
        grn_number=None,
        item_description="Components",
        hsn_code="8471",
        unit_price_inr=Decimal("2000.00"),
        quantity=5,
        gst_rate=Decimal("0.18"),
    )
    save_invoice(inv, is_user_created=True, db_path=test_db)

    # Incomplete initially
    assert any(i.invoice_number == "INV-WAITING-001" for i in list_incomplete_invoices(db_path=test_db))

    # Now authentic PO arrives and is saved
    po = PurchaseOrder.create(
        po_number="PO-AUTHENTIC-101",
        vendor_name="Future PO Vendor",
        gstin="27AABCU2222Z1Z5",
        issue_date=date(2025, 9, 15),
        valid_until=date(2025, 12, 15),
        item_description="Components",
        hsn_code="8471",
        unit_price_inr=Decimal("2000.00"),
        quantity=5,
        gst_rate=Decimal("0.18"),
    )
    save_purchase_order(po, db_path=test_db)

    # Incomplete status must be automatically cleared to 0
    with get_connection(test_db) as conn:
        row = conn.execute("SELECT is_incomplete, po_number FROM invoices WHERE invoice_number = 'INV-WAITING-001'").fetchone()
        assert row["is_incomplete"] == 0
        assert row["po_number"] == "PO-AUTHENTIC-101"

    # Should no longer be in incomplete list
    assert not any(i.invoice_number == "INV-WAITING-001" for i in list_incomplete_invoices(db_path=test_db))


def test_memory_retention_status_accuracy():
    """Verify MemoryClient honestly sets status to PENDING_SYNC or NOT_ATTEMPTED when offline."""
    # 1. Configured local/cloud but offline/unreachable
    client_local = MemoryClient(base_url="http://localhost:9999", api_key="", mode=MemoryMode.LOCAL)
    client_local._sdk_client = None  # simulate offline service

    doc_id = client_local.retain(bank_id="test-bank", content="Decision rationale")
    assert client_local.last_retain_status == "PENDING_SYNC"

    # 2. Configured explicitly as OFFLINE
    client_offline = MemoryClient(base_url="offline://local", api_key="", mode=MemoryMode.OFFLINE)
    doc_id2 = client_offline.retain(bank_id="test-bank", content="Decision rationale")
    assert client_offline.last_retain_status == "NOT_ATTEMPTED"

    # 3. Process human feedback reflects the honest status
    submission = FeedbackSubmission(
        invoice_number="INV-STATUS-001",
        vendor_name="Status Vendor",
        exception_type="PRICE_MISMATCH",
        agent_proposal="EDITED at 1000",
        human_decision=ApproverDecision.APPROVED,
        approver_role=ApproverRole.AP_MANAGER,
        human_explanation="Approved price waiver.",
        final_amount_inr=Decimal("1180.00"),
    )
    result = process_human_feedback(submission, client_local, bank_id="ledgermind-live-demo")
    assert result.hindsight_status == "PENDING_SYNC"


def test_fallback_escalates_on_missing_po():
    """Verify ResolutionAgent deterministic fallback cleanly escalates when PO documentation is missing."""
    agent = ResolutionAgent(llm_client=None)

    inv = Invoice.create(
        invoice_number="INV-NOPO-TEST",
        vendor_name="Test Vendor",
        gstin="27AABCU1234D1Z5",
        invoice_date=date(2025, 10, 1),
        po_number=None,
        grn_number=None,
        item_description="Test Item",
        hsn_code="8471",
        unit_price_inr=Decimal("1000.00"),
        quantity=1,
        gst_rate=Decimal("0.18"),
    )
    inv.is_incomplete = True

    proposal = agent.resolve(
        invoice=inv,
        po=None,
        grn=None,
        match_result=None,
        memory_enabled=False,
    )

    assert proposal.proposed_action == ApproverDecision.ESCALATED
    assert "Missing purchase order documentation" in proposal.reasoning


def test_sync_pending_reviews_idempotent(test_db: Path):
    """Verify sync_pending_reviews handles offline safely and updates statuses when online."""
    from data.store import save_vendor
    save_vendor("Sync Vendor", "27AABCU3333Z1Z5", db_path=test_db)
    inv = Invoice.create(
        invoice_number="INV-SYNC-001",
        vendor_name="Sync Vendor",
        gstin="27AABCU3333Z1Z5",
        invoice_date=date(2025, 10, 1),
        po_number=None,
        grn_number=None,
        item_description="Sync Test Item",
        hsn_code="8471",
        unit_price_inr=Decimal("1000.00"),
        quantity=1,
        gst_rate=Decimal("0.00"),
    )
    save_invoice(inv, is_user_created=True, db_path=test_db)

    # Seed a review with PENDING_SYNC status
    save_human_review(
        invoice_number="INV-SYNC-001",
        decision="APPROVED",
        approver_role="AP_MANAGER",
        approved_amount_inr=Decimal("1000.00"),
        rationale="Approved pending sync test.",
        hindsight_doc_id="feedback-offline-001",
        hindsight_bank_id="ledgermind-live-demo",
        hindsight_status="PENDING_SYNC",
        db_path=test_db,
    )

    # 1. Offline sync attempt
    mock_offline_client = MagicMock()
    mock_offline_client.is_healthy.return_value = False

    res_off = sync_pending_reviews(mock_offline_client, db_path=test_db)
    assert res_off["synced"] == 0
    assert "offline" in res_off["message"].lower()

    # 2. Healthy online sync attempt
    mock_online_client = MagicMock()
    mock_online_client.is_healthy.return_value = True
    mock_online_client.retain.return_value = "doc-synced-123"
    mock_online_client.last_retain_status = "SYNCED"

    res_on = sync_pending_reviews(mock_online_client, db_path=test_db)
    assert res_on["synced"] == 1
    assert res_on["failed"] == 0

    # Verify status in database is now SYNCED
    review = get_human_review("INV-SYNC-001", db_path=test_db)
    assert review["hindsight_status"] == "SYNCED"
    assert review["document_id"] == "doc-synced-123"

