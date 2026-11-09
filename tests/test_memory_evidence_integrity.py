"""
tests/test_memory_evidence_integrity.py
────────────────────────────────────────────────────────────────────────────────
Regression tests for Milestone 6 Memory Evidence Integrity:
  1. Prevents legal entity stopwords ("Pvt Ltd", "LLP", "Co") from collapsing
     distinct vendors to Prabhav Infosystems in get_vendor_slug().
  2. Ensures cross-vendor precedents are accurately identified and tagged with
     their genuine vendor identity, not the queried vendor.
  3. Verifies that multiple sub-facts from a single retained document collapse
     into exactly one deduplicated representative card in resolver evidence.
  4. Confirms that cross-vendor precedents are excluded from vendor-specific
     confidence calculations to prevent statistical dilution.
  5. Validates UI vendor badge resolution (cross-vendor vs direct precedent).
"""

from decimal import Decimal
import pytest

from agent.confidence import calculate_confidence, ConfidenceBand, is_memory_in_scope
from agent.resolver import normalize_and_deduplicate_memories
from data.models import ApproverDecision, ExceptionType
from data.vendors import ALL_VENDORS, get_vendor_slug
from memory.schema import RecalledMemory
from ui.components.cards import get_memory_vendor_info


def test_vendor_slug_legal_entity_stopwords_no_collision():
    """Verify that common corporate suffixes (Pvt Ltd, Co, LLP) never map arbitrary companies to Prabhav."""
    # Zenith has 'Pvt Ltd', Prabhav has 'Pvt Ltd'
    zenith_slug = get_vendor_slug("Zenith Precision Engineering Pvt Ltd")
    assert zenith_slug == "zenith-precision-engineering"
    assert zenith_slug != "prabhav-infosystems"

    # Nova Tech Supplies has 'Supplies', Kamalnath Supplies has 'Supplies'
    nova_slug = get_vendor_slug("Nova Tech Supplies")
    assert nova_slug == "nova-tech-supplies"
    assert nova_slug != "kamalnath-supplies"

    # All canonical vendors map to their exact slugs
    for v in ALL_VENDORS:
        assert get_vendor_slug(v.name) == v.slug
        assert get_vendor_slug(v.slug) == v.slug


def test_cross_vendor_memory_in_prabhav_query_scope():
    """
    When a Zenith price mismatch precedent appears during a Prabhav recall,
    it must be recognized as out-of-scope for Prabhav's vendor-specific score.
    """
    prabhav_mem = RecalledMemory(
        id="mem-pi-001",
        document_id="decision-INV-PI-2024-001",
        text="Prabhav Infosystems submitted invoice with 2% price overcharge. Approver decision: EDITED.",
        tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
        metadata={"vendor_name": "Prabhav Infosystems Pvt Ltd", "decision": "EDITED"},
    )

    zenith_mem = RecalledMemory(
        id="mem-zenith-001",
        document_id="feedback-INV-ZENITH-2025-101",
        text="Zenith Precision Engineering invoice exceeded contract by 8%. Human decision by AP_CLERK: REJECTED.",
        tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected"],
        metadata={"vendor_name": "Zenith Precision Engineering Pvt Ltd", "decision": "REJECTED"},
    )

    # Prabhav memory is in scope for Prabhav
    assert is_memory_in_scope(prabhav_mem, expected_vendor_slug="prabhav-infosystems", expected_exception_type=ExceptionType.PRICE_MISMATCH) is True

    # Zenith memory is OUT OF SCOPE for Prabhav
    assert is_memory_in_scope(zenith_mem, expected_vendor_slug="prabhav-infosystems", expected_exception_type=ExceptionType.PRICE_MISMATCH) is False


def test_sub_fact_deduplication_single_document():
    """
    Multiple sub-facts from the same document (some with document_id=None)
    must collapse to a single representative card, preventing evidence flooding.
    """
    sub_facts = [
        RecalledMemory(
            id="sub-1",
            document_id=None,
            text="The review was for a PRICE_MISMATCH exception.",
            tags=["vendor:zenith-precision-engineering", "source:human_feedback"],
            metadata={},
            score=0.70,
        ),
        RecalledMemory(
            id="sub-2",
            document_id="feedback-INV-ZENITH-2025-101",
            text="Invoice INV-ZENITH-2025-101 from Zenith Precision Engineering Pvt Ltd was reviewed. Decision: REJECTED.",
            tags=["vendor:zenith-precision-engineering", "source:human_feedback"],
            metadata={"invoice_number": "INV-ZENITH-2025-101", "vendor_name": "Zenith Precision Engineering Pvt Ltd"},
            score=0.92,
        ),
        RecalledMemory(
            id="sub-3",
            document_id=None,
            text="Invoice INV-ZENITH-2025-101 had an overcharge of 8.0%.",
            tags=["vendor:zenith-precision-engineering", "source:human_feedback"],
            metadata={},
            score=0.85,
        ),
        RecalledMemory(
            id="sub-4",
            document_id="decision-INV-PI-2024-001",
            text="Prabhav Infosystems invoice INV-PI-2024-001 was approved as EDITED.",
            tags=["vendor:prabhav-infosystems", "decision:edited"],
            metadata={"invoice_number": "INV-PI-2024-001"},
            score=0.90,
        ),
    ]

    deduped = normalize_and_deduplicate_memories(sub_facts, max_items=5)

    # Exactly 2 unique documents: 1 Zenith, 1 Prabhav
    assert len(deduped) == 2
    doc_ids = {m.document_id for m in deduped}
    assert doc_ids == {"feedback-INV-ZENITH-2025-101", "decision-INV-PI-2024-001"}

    # The chosen Zenith memory is the most informative one with metadata
    zenith_chosen = next(m for m in deduped if m.document_id == "feedback-INV-ZENITH-2025-101")
    assert zenith_chosen.metadata.get("vendor_name") == "Zenith Precision Engineering Pvt Ltd"


def test_confidence_calculation_excludes_cross_vendor_decisions():
    """
    Confidence score for Prabhav must only count in-scope Prabhav decisions,
    correctly excluding cross-vendor precedents without crashing or misrepresenting consistency.
    """
    sample = [
        RecalledMemory(
            id="pi-1",
            document_id="decision-INV-PI-2024-001",
            text="Decision by AP_MANAGER: EDITED.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
            metadata={"vendor_name": "Prabhav Infosystems Pvt Ltd", "decision": "EDITED"},
        ),
        RecalledMemory(
            id="pi-2",
            document_id="decision-INV-PI-2024-002",
            text="Decision by AP_MANAGER: EDITED.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
            metadata={"vendor_name": "Prabhav Infosystems Pvt Ltd", "decision": "EDITED"},
        ),
        RecalledMemory(
            id="pi-3",
            document_id="decision-INV-PI-2024-003",
            text="Decision by AP_MANAGER: EDITED.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
            metadata={"vendor_name": "Prabhav Infosystems Pvt Ltd", "decision": "EDITED"},
        ),
        RecalledMemory(
            id="zen-1",
            document_id="feedback-INV-ZENITH-2025-101",
            text="Decision by AP_CLERK: REJECTED.",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected"],
            metadata={"vendor_name": "Zenith Precision Engineering Pvt Ltd", "decision": "REJECTED"},
        ),
    ]

    conf = calculate_confidence(
        proposed_decision=ApproverDecision.EDITED,
        historical_memories=sample,
        expected_vendor_slug="prabhav-infosystems",
        expected_exception_type=ExceptionType.PRICE_MISMATCH,
    )

    # 3 in-scope decisions, 1 excluded (Zenith)
    assert conf.sample_size_n == 3
    assert conf.agreement_count == 3
    assert conf.consistency == 1.0
    assert conf.band == ConfidenceBand.HIGH
    assert conf.decision_breakdown == {"EDITED": 3}
    assert conf.excluded_memories_count == 1
    assert "feedback-INV-ZENITH-2025-101" not in conf.supporting_document_ids
    assert "decision-INV-PI-2024-001" in conf.supporting_document_ids


def test_ui_vendor_attribution_and_cross_vendor_detection():
    """Verify UI helper accurately extracts vendor name and flags cross-vendor precedents."""
    zenith_mem = RecalledMemory(
        id="zenith-1",
        document_id="feedback-INV-ZENITH-2025-101",
        text="Invoice INV-ZENITH-2025-101 from Zenith Precision Engineering Pvt Ltd.",
        tags=["vendor:zenith-precision-engineering", "exception:price_mismatch"],
        metadata={"vendor_name": "Zenith Precision Engineering Pvt Ltd"},
    )

    v_name, v_slug = get_memory_vendor_info(zenith_mem)
    assert v_name == "Zenith Precision Engineering Pvt Ltd"
    assert v_slug == "zenith-precision-engineering"

    # In a Prabhav query, Zenith is cross-vendor
    target_slug = get_vendor_slug("Prabhav Infosystems Pvt Ltd")
    assert (v_slug != target_slug) is True

    # In a Zenith query, Zenith is direct precedent
    target_slug_zen = get_vendor_slug("Zenith Precision Engineering Pvt Ltd")
    assert (v_slug != target_slug_zen) is False
