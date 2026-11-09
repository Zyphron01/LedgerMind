"""
tests/test_ui_controllers.py
────────────────────────────────────────────────────────────────────────────────
Unit tests for LedgerMind Streamlit UI controllers and state providers.
Verifies data loading, health inspection, and benchmark label secrecy.
"""

from decimal import Decimal
import pytest

from data.synthetic import load_held_out_invoices
from ui.state import (
    check_hindsight_health,
    get_held_out_by_id,
    get_held_out_invoices,
    get_hindsight_document_count,
    init_session_state,
)
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID


def test_ui_held_out_invoices_loading():
    """Verify that all 20 benchmark held-out invoices are loaded cleanly alongside user records."""
    all_invoices = get_held_out_invoices()
    assert len(all_invoices) >= 20
    sample_invoices = [inv for inv in all_invoices if not getattr(inv, "is_user_created", False)]
    assert len(sample_invoices) == 20
    assert sample_invoices[0].invoice.invoice_number == "INV-PI-2025-101"


def test_ui_get_held_out_by_id():
    """Verify lookup by invoice number."""
    item = get_held_out_by_id("INV-PI-2025-101")
    assert item is not None
    assert item.invoice.vendor_name == "Prabhav Infosystems Pvt Ltd"

    item_none = get_held_out_by_id("NON_EXISTENT_ID")
    assert item_none is None


def test_ui_health_check_structure():
    """Verify health check returns valid contract keys."""
    health = check_hindsight_health()
    assert isinstance(health, dict)
    assert "status" in health
    assert "connected" in health
    assert "url" in health


def test_ui_bank_document_counting():
    """Verify document counting function executes without exception."""
    docs, facts = get_hindsight_document_count(BASELINE_EVAL_BANK_ID)
    assert isinstance(docs, int)
    assert isinstance(facts, int)
    assert docs >= 0
    assert facts >= 0


def test_expected_resolution_label_secrecy():
    """Verify that benchmark ground truth labels are isolated from standard queue display."""
    invoices = get_held_out_invoices()
    for inv in invoices:
        # Expected resolution must exist on object for offline benchmarks
        assert hasattr(inv, "expected_resolution")
        # But invoice and match_result objects themselves must not contain the label
        inv_dict = inv.invoice.model_dump()
        match_dict = inv.match_result.model_dump()
        assert "expected_resolution" not in inv_dict
        assert "expected_action" not in inv_dict
        assert "expected_action" not in match_dict

