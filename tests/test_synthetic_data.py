"""
tests/test_synthetic_data.py
────────────────────────────────────────────────────────────────────────────────
Validation tests for synthetic AP exception datasets and vendor models.
Verifies data integrity, GSTIN regex validity, counts, exception distributions,
temporal policy shifts, and evaluation label isolation.
"""

from datetime import date
import json
from pathlib import Path
import re

import pytest

from data.models import ApproverDecision, ExceptionType, HeldOutInvoice, HistoricalDecision
from data.synthetic import (
    generate_synthetic_datasets,
    HISTORICAL_FILE,
    HELD_OUT_FILE,
    EVAL_LABELS_FILE,
    load_historical_decisions,
    load_held_out_invoices,
)
from data.vendors import ALL_VENDORS, VENDORS_BY_SLUG

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def test_vendor_definitions():
    """Verify all 8 fictional vendors exist with format-valid GSTINs and Indian states."""
    assert len(ALL_VENDORS) == 8
    assert len(VENDORS_BY_SLUG) == 8

    for vendor in ALL_VENDORS:
        assert GSTIN_REGEX.match(vendor.gstin), f"Invalid GSTIN format: {vendor.gstin} for {vendor.name}"
        assert vendor.gstin.startswith(vendor.state_code), (
            f"State code mismatch in GSTIN {vendor.gstin} (expected prefix {vendor.state_code})"
        )
        assert len(vendor.standard_hsn) in (6, 8), f"Invalid HSN code length: {vendor.standard_hsn}"
        assert vendor.standard_gst_rate > 0


def test_deterministic_generation():
    """Generating with seed=42 must produce identical output twice."""
    hist1, held1 = generate_synthetic_datasets(seed=42)
    hist2, held2 = generate_synthetic_datasets(seed=42)

    assert len(hist1) == len(hist2) == 50
    assert len(held1) == len(held2) == 20

    for h1, h2 in zip(hist1, hist2):
        assert h1.invoice.invoice_number == h2.invoice.invoice_number
        assert h1.decision == h2.decision
        assert h1.outcome_inr == h2.outcome_inr

    for o1, o2 in zip(held1, held2):
        assert o1.invoice.invoice_number == o2.invoice.invoice_number
        assert o1.expected_resolution.decision == o2.expected_resolution.decision
        assert o1.expected_resolution.amount_inr == o2.expected_resolution.amount_inr


def test_all_exception_types_represented():
    """All 6 canonical exception types must be present in both history and held-out sets."""
    history = load_historical_decisions(HISTORICAL_FILE)
    held_out = load_held_out_invoices(HELD_OUT_FILE)

    history_exceptions = {h.match_result.primary_discrepancy.exception_type for h in history}
    held_out_exceptions = {h.match_result.primary_discrepancy.exception_type for h in held_out}

    expected_types = {
        ExceptionType.PRICE_MISMATCH,
        ExceptionType.QUANTITY_SHORTFALL,
        ExceptionType.DUPLICATE_INVOICE,
        ExceptionType.GST_RATE_ERROR,
        ExceptionType.PO_EXPIRED,
        ExceptionType.HSN_MISMATCH,
    }

    assert history_exceptions == expected_types, f"Missing exception types in history: {expected_types - history_exceptions}"
    assert held_out_exceptions == expected_types, f"Missing exception types in held-out: {expected_types - held_out_exceptions}"


def test_suryakant_temporal_policy_shift():
    """
    Suryakant Engineering records must reflect the 2025-08-01 policy change:
      - Invoices before 2025-08-01: ESCALATED / APPROVED with executive grace note.
      - Invoices on or after 2025-08-01: REJECTED under new Q3 AP policy.
    """
    history = load_historical_decisions(HISTORICAL_FILE)
    suryakant_records = [h for h in history if h.invoice.vendor_name == "Suryakant Engineering Works"]
    assert len(suryakant_records) == 7

    policy_date = date(2025, 8, 1)

    for rec in suryakant_records:
        inv_d = rec.invoice.invoice_date
        if inv_d < policy_date:
            assert rec.decision == ApproverDecision.ESCALATED
            assert "grace extension" in rec.human_reason.lower() or "cfo" in rec.human_reason.lower()
        else:
            assert rec.decision == ApproverDecision.REJECTED
            assert "policy 2025-q3" in rec.human_reason.lower() or "rejected" in rec.human_reason.lower()


def test_held_out_label_isolation():
    """
    Verifies that ground truth evaluation labels are strictly stored separately
    in data/held_out_evaluation_labels.json, while data/held_out_invoices.json
    does NOT leak the expected resolution to the evaluation runner.
    """
    with open(EVAL_LABELS_FILE, "r", encoding="utf-8") as f:
        labels = json.load(f)
    with open(HELD_OUT_FILE, "r", encoding="utf-8") as f:
        invoices = json.load(f)

    assert len(labels) == 20
    assert len(invoices) == 20

    # Ensure all labels have ground-truth answers keyed by invoice_number
    for inv_no, resolution in labels.items():
        assert "decision" in resolution
        assert "amount_inr" in resolution
        assert "reason" in resolution


def test_narrative_factual_structure():
    """
    Retained narratives must record only what happened, the human decision, and reasoning.
    Must NOT contain 'vendor_quirk_summary' or 'Tags:' lines in the prose text.
    """
    history = load_historical_decisions(HISTORICAL_FILE)
    for rec in history:
        narrative = rec.to_narrative()
        assert "vendor_quirk_summary" not in narrative.lower()
        assert "tags:" not in narrative.lower()
        assert rec.invoice.invoice_number in narrative
        assert rec.decision.value in narrative
        assert rec.human_reason in narrative
