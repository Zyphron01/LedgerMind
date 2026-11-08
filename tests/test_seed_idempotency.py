"""
tests/test_seed_idempotency.py
────────────────────────────────────────────────────────────────────────────────
Unit tests for LedgerMind's Hindsight seeding engine and idempotency ledger.
Validates SHA-256 keys, cross-bank separation, ledger persistence, skip logic,
and strict safety isolation of held-out evaluation invoices.
"""

import json
from pathlib import Path
import pytest
import tempfile

from data.seed import (
    compute_idempotency_key,
    SeedLedger,
    seed_historical_records,
)
from data.models import HistoricalDecision
from data.synthetic import load_historical_decisions


def test_compute_idempotency_key():
    """Validates deterministic SHA-256 hashing for bank_id and invoice_number."""
    k1 = compute_idempotency_key("bank-alpha", "INV-2025-001")
    k2 = compute_idempotency_key("bank-alpha", "INV-2025-001")
    assert k1 == k2
    assert len(k1) == 64  # SHA-256 hex string length

    # Different invoice in same bank produces different key
    k3 = compute_idempotency_key("bank-alpha", "INV-2025-002")
    assert k1 != k3

    # Cross-bank isolation: same invoice in different banks must produce different keys
    k4 = compute_idempotency_key("bank-beta", "INV-2025-001")
    assert k1 != k4


def test_seed_ledger_persistence(tmp_path: Path):
    """Tests writing to and querying the SeedLedger."""
    temp_ledger = tmp_path / "test_ledger.json"
    ledger = SeedLedger(ledger_path=temp_ledger)

    bank = "test-bank-1"
    inv_no = "INV-SEW-2025-001"

    assert not ledger.is_seeded(bank, inv_no)

    ledger.record_seeded(
        bank_id=bank,
        invoice_number=inv_no,
        document_id="decision-INV-SEW-2025-001",
        vendor_name="Suryakant Engineering Works",
        exception_type="PO_EXPIRED",
        decision="REJECTED",
    )

    assert ledger.is_seeded(bank, inv_no)

    # Reload from disk into a new instance to verify serialization
    reloaded_ledger = SeedLedger(ledger_path=temp_ledger)
    assert reloaded_ledger.is_seeded(bank, inv_no)
    # Check that another bank does not show as seeded
    assert not reloaded_ledger.is_seeded("test-bank-2", inv_no)


def test_seed_ledger_reset_bank(tmp_path: Path):
    """Tests resetting records for one bank leaves other banks untouched."""
    temp_ledger = tmp_path / "test_ledger.json"
    ledger = SeedLedger(ledger_path=temp_ledger)

    ledger.record_seeded("bank-a", "INV-001", "doc-1", "V1", "E1", "D1")
    ledger.record_seeded("bank-b", "INV-002", "doc-2", "V2", "E2", "D2")

    assert ledger.is_seeded("bank-a", "INV-001")
    assert ledger.is_seeded("bank-b", "INV-002")

    cleared = ledger.reset_bank("bank-a")
    assert cleared == 1
    assert not ledger.is_seeded("bank-a", "INV-001")
    assert ledger.is_seeded("bank-b", "INV-002")


def test_safety_guard_blocks_held_out_invoices(tmp_path: Path):
    """
    If any invoice in the batch belongs to the held-out set,
    seed_historical_records must immediately raise a ValueError.
    """
    # Create a dummy historical file containing a held-out invoice
    fake_history_file = tmp_path / "fake_history.json"
    real_history = load_historical_decisions()
    # Replace the first invoice's number with a held-out invoice number
    held_out_inv_no = "INV-PI-2025-101"  # From held-out set
    poisoned_item = real_history[0].model_dump(mode="json")
    poisoned_item["invoice"]["invoice_number"] = held_out_inv_no

    with open(fake_history_file, "w", encoding="utf-8") as f:
        json.dump([poisoned_item], f)

    with pytest.raises(ValueError, match="FATAL SAFETY VIOLATION"):
        seed_historical_records(
            bank_id="test-bank",
            historical_path=str(fake_history_file),
            dry_run=True,
        )


def test_dry_run_mode():
    """Dry-run must simulate without modifying the persistent ledger."""
    summary = seed_historical_records(
        bank_id="test-dry-run-bank",
        sample_limit=3,
        dry_run=True,
    )
    assert summary["total_records"] == 3
    assert summary["seeded_count"] == 3
    assert summary["skipped_count"] == 0
    assert summary["error_count"] == 0
    assert all(r["status"] == "DRY_RUN" for r in summary["records"])

