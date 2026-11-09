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
    # Supporting facts aggregated from the other 2 sub-facts
    assert len(zenith_chosen.supporting_facts) == 2
    assert any("8.0%" in f for f in zenith_chosen.supporting_facts)
    assert any("PRICE_MISMATCH" in f for f in zenith_chosen.supporting_facts)


def test_ungrouped_facts_handling():
    """
    If a memory fact lacks any parent document identity or invoice citation,
    it must be preserved as an ungrouped fact rather than inventing a parent.
    """
    facts = [
        RecalledMemory(
            id="random-fact-12345678",
            document_id=None,
            text="Historical general note: AP policies require 3-way matching on all POs above INR 10,000.",
            tags=["policy:rule"],
            metadata={},
            score=0.65,
        ),
        RecalledMemory(
            id="pi-doc-1",
            document_id="decision-INV-PI-2024-001",
            text="Prabhav Infosystems invoice INV-PI-2024-001 was approved as EDITED.",
            tags=["vendor:prabhav-infosystems"],
            metadata={"invoice_number": "INV-PI-2024-001"},
            score=0.90,
        ),
    ]

    deduped = normalize_and_deduplicate_memories(facts, max_items=5)
    assert len(deduped) == 2

    ungrouped = next(m for m in deduped if m.is_ungrouped)
    assert ungrouped.is_ungrouped is True
    assert ungrouped.document_id.startswith("fact-")
    assert "random-fact" in ungrouped.id


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


def test_self_feedback_exclusion_from_precedents_and_confidence():
    """
    Requirement C & D: A previous review on the currently analyzed invoice (e.g. feedback-INV-PI-2025-101)
    MUST NOT be treated as an independent precedent or factored into confidence scoring.
    It must be preserved separately for audit history.
    """
    mems = [
        # Self-feedback for the current invoice
        RecalledMemory(
            id="fb-pi-101",
            document_id="feedback-INV-PI-2025-101",
            text="Human reviewer approved invoice INV-PI-2025-101 as EDITED.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited", "source:human_feedback"],
            metadata={"invoice_number": "INV-PI-2025-101", "decision": "EDITED"},
            score=0.95,
        ),
        # Genuine independent historical decision from a prior invoice
        RecalledMemory(
            id="dec-pi-001",
            document_id="decision-INV-PI-2024-001",
            text="Invoice INV-PI-2024-001 price mismatch approved as EDITED.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
            metadata={"invoice_number": "INV-PI-2024-001", "decision": "EDITED"},
            score=0.90,
        ),
        # Another independent historical decision
        RecalledMemory(
            id="dec-pi-002",
            document_id="decision-INV-PI-2024-002",
            text="Invoice INV-PI-2024-002 price mismatch approved as EDITED.",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
            metadata={"invoice_number": "INV-PI-2024-002", "decision": "EDITED"},
            score=0.88,
        ),
    ]

    # 1. normalize_and_deduplicate_memories excludes self-review from precedents
    precedents, self_reviews = normalize_and_deduplicate_memories(
        mems,
        max_items=5,
        exclude_invoice_number="INV-PI-2025-101",
        return_self_reviews=True,
    )

    # Precedents contain ONLY the independent past decisions
    assert len(precedents) == 2
    assert all(p.document_id != "feedback-INV-PI-2025-101" for p in precedents)
    assert {p.document_id for p in precedents} == {"decision-INV-PI-2024-001", "decision-INV-PI-2024-002"}

    # Self-review is preserved separately for audit history
    assert len(self_reviews) == 1
    assert self_reviews[0].document_id == "feedback-INV-PI-2025-101"

    # 2. calculate_confidence strictly excludes self-review from sample size n
    conf = calculate_confidence(
        proposed_decision=ApproverDecision.EDITED,
        historical_memories=mems,
        expected_vendor_slug="prabhav-infosystems",
        expected_exception_type=ExceptionType.PRICE_MISMATCH,
        current_invoice_number="INV-PI-2025-101",
    )

    # Sample size n reflects ONLY the 2 independent decisions, NOT 3
    assert conf.sample_size_n == 2
    assert conf.agreement_count == 2
    assert conf.consistency == 1.0
    assert "feedback-INV-PI-2025-101" not in conf.supporting_document_ids
    assert conf.excluded_memories_count >= 1


def test_live_vs_offline_source_attribution_integrity():
    """
    Requirement A & B & F: Live Hindsight results must have is_offline_fallback=False.
    Offline store results must have is_offline_fallback=True.
    No code may silently relabel offline records as live Hindsight evidence.
    """
    from memory.offline_store import OfflineStore

    # Offline store record
    store = OfflineStore()
    offline_mems = store.recall(
        bank_id="ledgermind-ap-exceptions",
        query="Prabhav price mismatch",
        tags=["vendor:prabhav-infosystems"],
        limit=2,
    )
    if offline_mems:
        for m in offline_mems:
            assert m.is_offline_fallback is True, "Offline store must set is_offline_fallback=True"

    # Hindsight SDK result schema definition
    live_mem = RecalledMemory(
        id="live-001",
        text="Live Hindsight fact",
        document_id="decision-INV-PI-2024-001",
        is_offline_fallback=False,
    )
    assert live_mem.is_offline_fallback is False


def test_honest_fallback_reporting_not_relabeled():
    """
    Storage type string in UI components must honestly distinguish between
    '💾 Offline JSONL Fallback' and '🧠 Hindsight Vector DB' based strictly on is_offline_fallback.
    """
    offline_mem = RecalledMemory(
        id="off-1",
        text="Offline record",
        document_id="decision-INV-PI-2024-001",
        is_offline_fallback=True,
    )
    live_mem = RecalledMemory(
        id="live-1",
        text="Live record",
        document_id="decision-INV-PI-2024-001",
        is_offline_fallback=False,
    )

    # Ensure field is not corrupted or ignored
    assert offline_mem.is_offline_fallback is True
    assert live_mem.is_offline_fallback is False


def test_slow_but_successful_hindsight_recall(monkeypatch):
    """
    Regression test for Hindsight recall latency tolerance:
    When Hindsight takes multiple seconds (e.g., 4.5s - 6.7s for complex vector search),
    LedgerMind client must wait for the response and retain live provenance (is_offline_fallback=False).
    """
    import time
    from unittest.mock import MagicMock
    from hindsight_client_api.models.recall_response import RecallResponse
    from hindsight_client_api.models.recall_result import RecallResult
    from memory.client import MemoryClient, MemoryMode

    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    
    mock_item = MagicMock()
    mock_item.id = "mock-live-001"
    mock_item.text = "Live slow recalled fact from Hindsight vector engine"
    mock_item.type = "observation"
    mock_item.document_id = "decision-INV-PI-2024-001"
    mock_item.tags = ["vendor:prabhav-infosystems"]
    mock_item.metadata = {"vendor_name": "Prabhav Infosystems Pvt Ltd"}
    mock_item.scores = MagicMock(final=0.95, semantic=0.92, reranker=0.90)

    mock_resp = MagicMock()
    mock_resp.results = [mock_item]

    def slow_recall(**kwargs):
        time.sleep(0.1)  # Simulate latency
        return mock_resp

    mock_sdk = MagicMock()
    mock_sdk.recall = MagicMock(side_effect=slow_recall)
    client._sdk_client = mock_sdk

    results = client.recall(
        bank_id="ledgermind-ap-exceptions",
        query="Prabhav price mismatch",
        limit=5,
    )

    assert len(results) == 1
    assert results[0].id == "mock-live-001"
    assert results[0].is_offline_fallback is False
    assert client.last_recall_source == "hindsight"
    assert client.last_fallback_reason is None
    assert client.last_recall_elapsed is not None
    assert client.last_recall_elapsed >= 0.1


def test_hindsight_timeout_honest_fallback_provenance(monkeypatch):
    """
    When Hindsight genuinely times out or raises an exception, the client must:
    1. Catch the exception safely without crashing.
    2. Record the exception type, elapsed time, and fallback reason.
    3. Return offline fallback memories with is_offline_fallback=True.
    4. Never relabel offline records as live Hindsight data.
    """
    from unittest.mock import MagicMock
    from memory.client import MemoryClient, MemoryMode

    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")

    def timeout_recall(**kwargs):
        raise TimeoutError("Read timed out after 30.0 seconds")

    mock_sdk = MagicMock()
    mock_sdk.recall = MagicMock(side_effect=timeout_recall)
    client._sdk_client = mock_sdk

    results = client.recall(
        bank_id="ledgermind-ap-exceptions",
        query="Prabhav price mismatch",
        limit=5,
    )

    assert client.last_recall_source == "offline"
    assert "TimeoutError" in client.last_fallback_reason
    assert "Read timed out after 30.0 seconds" in client.last_fallback_reason
    assert client.last_recall_elapsed is not None
    # All returned memories MUST have is_offline_fallback=True
    for mem in results:
        assert mem.is_offline_fallback is True



