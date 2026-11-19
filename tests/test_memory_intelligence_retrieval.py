"""
tests/test_memory_intelligence_retrieval.py
────────────────────────────────────────────────────────────────────────────────
Regression tests for Memory Intelligence retrieval, vendor slug aliasing,
provenance transparency, and reflect cache hygiene.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.vendors import get_vendor_slug
from memory.budget_guard import BudgetGuard
from memory.client import MemoryClient
from memory.operations import get_vendor_profile, recall_vendor_history
from memory.reflect_cache import ReflectCache
from memory.schema import MemoryMode, ReflectSummary
from ui.state import init_session_state, navigate_to


def test_zenith_memory_retrieval_in_live_demo():
    """Verify that Zenith review feedback is retrieved from ledgermind-live-demo."""
    client = MemoryClient(mode=MemoryMode.OFFLINE)
    vendor_name = "Zenith Precision Engineering Pvt Ltd"
    vendor_slug = "zenith-precision-engineering-pvt-ltd"

    recalled = recall_vendor_history(
        client=client,
        bank_id=LIVE_DEMO_BANK_ID,
        vendor_name=vendor_name,
        vendor_slug=vendor_slug,
        limit=15,
    )

    assert len(recalled) >= 1
    zenith_doc = next((m for m in recalled if m.document_id == "feedback-INV-ZENITH-2025-101"), None)
    assert zenith_doc is not None, "feedback-INV-ZENITH-2025-101 must be retrieved"
    assert "vendor:zenith-precision-engineering" in zenith_doc.tags
    assert zenith_doc.metadata.get("decision") == "REJECTED"


def test_zenith_memory_retrieval_in_baseline_is_clean_empty():
    """Verify that Zenith returns 0 records in baseline bank without errors."""
    client = MemoryClient(mode=MemoryMode.OFFLINE)
    vendor_name = "Zenith Precision Engineering Pvt Ltd"

    recalled = recall_vendor_history(
        client=client,
        bank_id=BASELINE_EVAL_BANK_ID,
        vendor_name=vendor_name,
        limit=15,
    )

    assert recalled == []


def test_vendor_slug_resolution_consistency():
    """Verify consistent slug canonicalization between benchmark and user-created vendors."""
    # Benchmark vendor with legal suffix
    assert get_vendor_slug("Prabhav Infosystems Pvt Ltd") == "prabhav-infosystems"
    # Benchmark vendor with trade suffix
    assert get_vendor_slug("Bhavna Textile Traders") == "bhavna-textiles"
    # User-created vendor with legal suffix
    assert get_vendor_slug("Zenith Precision Engineering Pvt Ltd") == "zenith-precision-engineering"
    assert get_vendor_slug("Apex Precision Tools Pvt Ltd") == "apex-precision-tools"


def test_reflect_failure_not_cached_to_disk(tmp_path: Path):
    """Verify that a failed reflect call never writes failure strings to disk cache."""
    cache_file = tmp_path / "test_reflect.json"
    budget_file = tmp_path / "test_budget.jsonl"
    cache = ReflectCache(cache_path=cache_file)
    budget = BudgetGuard(log_path=budget_file)

    client = MemoryClient(mode=MemoryMode.LOCAL, reflect_cache=cache, budget_guard=budget)
    client._sdk_client = MagicMock()
    client._sdk_client.reflect.side_effect = Exception("Rate limit or service failure")

    prof = client.reflect(LIVE_DEMO_BANK_ID, "zenith-precision-engineering")
    assert prof.is_error is True
    assert "Rate limit or service failure" in prof.error_message

    # Verify not in cache (scoped and unscoped)
    assert cache.get("zenith-precision-engineering", bank_id=LIVE_DEMO_BANK_ID) is None
    assert cache.get("zenith-precision-engineering") is None


def test_reflect_empty_exception_formatted_cleanly(tmp_path: Path):
    """Verify that an exception with an empty str() representation formats cleanly."""
    cache_file = tmp_path / "test_reflect.json"
    budget_file = tmp_path / "test_budget.jsonl"
    cache = ReflectCache(cache_path=cache_file)
    budget = BudgetGuard(log_path=budget_file)

    client = MemoryClient(mode=MemoryMode.LOCAL, reflect_cache=cache, budget_guard=budget)
    client._sdk_client = MagicMock()
    client._sdk_client.reflect.side_effect = RuntimeError()

    prof = client.reflect(LIVE_DEMO_BANK_ID, "nova-tech-supplies")
    assert prof.is_error is True
    assert "RuntimeError" in prof.summary
    assert "()" not in prof.summary
    assert cache.get("nova-tech-supplies", bank_id=LIVE_DEMO_BANK_ID) is None
    assert cache.get("nova-tech-supplies") is None


def test_reflect_cache_purges_corrupted_entries(tmp_path: Path):
    """Verify that ReflectCache automatically purges corrupted error strings."""
    cache_file = tmp_path / "corrupted_reflect.json"
    import json
    corrupted_data = {
        "valid-vendor": {
            "vendor_slug": "valid-vendor",
            "summary": "Valid synthesis summary for testing.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "failed-vendor-1": {
            "vendor_slug": "failed-vendor-1",
            "summary": "Reflect generation failed (); falling back to direct historical recall.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "failed-vendor-2": {
            "vendor_slug": "failed-vendor-2",
            "summary": "Reflect generation failed ((500) Reason: Internal Server Error); falling back...",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(corrupted_data, f)

    cache = ReflectCache(cache_path=cache_file)
    # Failed entries must be purged on load
    assert "failed-vendor-1" not in cache.data
    assert "failed-vendor-2" not in cache.data
    # Valid entry must be preserved
    assert "valid-vendor" in cache.data
    valid = cache.get("valid-vendor")
    assert valid is not None
    assert valid.summary == "Valid synthesis summary for testing."


def test_navigation_queue_to_workbench_state_contract():
    """Verify that queue-to-workbench pending navigation helper preserves contract."""
    from unittest.mock import patch
    import streamlit as st
    st.session_state.clear()
    init_session_state()
    with patch.object(st, "rerun"):
        navigate_to("Resolution Workbench", selected_invoice_id="INV-NOVA-2025-002")
    assert st.session_state.get("pending_page") == "Resolution Workbench"
    assert st.session_state.get("selected_invoice_id") == "INV-NOVA-2025-002"


def test_legacy_reflect_summary_without_is_error_attribute():
    """Verify backward compatibility: legacy instances missing is_error do not raise AttributeError."""
    prof = ReflectSummary(
        vendor_slug="zenith-precision-engineering",
        summary="Legacy summary without explicit error fields",
    )
    # Simulate an instance deserialized from older schema without is_error in instance dict
    if "is_error" in prof.__dict__:
        del prof.__dict__["is_error"]
    if "error_message" in prof.__dict__:
        del prof.__dict__["error_message"]

    # Direct attribute lookup must not raise AttributeError
    assert prof.is_error is False
    assert prof.error_message is None
    # getattr lookup must also succeed
    assert getattr(prof, "is_error", False) is False
    assert getattr(prof, "error_message", None) is None


def test_memory_intelligence_renders_with_legacy_reflect_object():
    """Verify that Memory Intelligence renders cleanly when encountering a legacy ReflectSummary."""
    from unittest.mock import patch
    import streamlit as st
    from ui.pages.memory_intelligence import render_memory_intelligence_page

    legacy_prof = ReflectSummary(
        vendor_slug="zenith-precision-engineering",
        summary="Reflect generation failed (); falling back to direct historical recall.",
    )
    if "is_error" in legacy_prof.__dict__:
        del legacy_prof.__dict__["is_error"]

    offline_client = MemoryClient(mode=MemoryMode.OFFLINE)
    with patch("ui.pages.memory_intelligence.get_memory_client", return_value=offline_client):
        with patch("ui.pages.memory_intelligence.get_vendor_profile", return_value=legacy_prof):
            with patch("streamlit.selectbox", return_value="Zenith Precision Engineering Pvt Ltd"):
                with patch("streamlit.radio", return_value=LIVE_DEMO_BANK_ID):
                    # Must render without AttributeError: 'ReflectSummary' object has no attribute 'is_error'
                    render_memory_intelligence_page()


def _build_mock_zenith_nine_records():
    """Build simulated set of 9 memories matching the live Hindsight response for Zenith."""
    from memory.schema import RecalledMemory
    return [
        RecalledMemory(
            id="obs-1",
            document_id=None,
            type="observation",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={},
            text="Zenith Precision Engineering Pvt Ltd is the vendor for invoice INV-ZENITH-2025-101.",
            score=0.88,
        ),
        RecalledMemory(
            id="world-1",
            document_id="feedback-INV-ZENITH-2025-101",
            type="world",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={"invoice_number": "INV-ZENITH-2025-101", "decision": "REJECTED", "vendor_name": "Zenith Precision Engineering Pvt Ltd"},
            text="Invoice INV-ZENITH-2025-101 from Zenith Precision Engineering Pvt Ltd was reviewed on 2026-11-09 for a PRICE_MISMATCH exception; the agent proposed REJECTED at ₹0.00 and the AP_CLERK human reviewer also REJECTED the invoice.",
            score=0.95,
        ),
        RecalledMemory(
            id="obs-2",
            document_id=None,
            type="observation",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={},
            text="AP_CLERK human reviewer also REJECTED the invoice INV-ZENITH-2025-101.",
            score=0.87,
        ),
        RecalledMemory(
            id="obs-3",
            document_id=None,
            type="observation",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={},
            text="The agent proposed REJECTED at ₹0.00 for invoice INV-ZENITH-2025-101.",
            score=0.85,
        ),
        RecalledMemory(
            id="obs-4",
            document_id=None,
            type="observation",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={},
            text="Invoice INV-ZENITH-2025-101 was reviewed on 2026-11-09 for a PRICE_MISMATCH exception.",
            score=0.84,
        ),
        RecalledMemory(
            id="obs-5",
            document_id=None,
            type="observation",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={},
            text="Invoice INV-ZENITH-2025-101 had an overcharge of 8.0%, exceeding the contractual limit of 1.0% under policy POL-AP-002.",
            score=0.83,
        ),
        RecalledMemory(
            id="obs-6",
            document_id=None,
            type="observation",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={},
            text="The final financial resolution set the amount to ₹0.00.",
            score=0.80,
        ),
        RecalledMemory(
            id="obs-7",
            document_id=None,
            type="observation",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={},
            text="The final financial resolution was due to an overcharge of 8.0% exceeding the contractual limit.",
            score=0.79,
        ),
        RecalledMemory(
            id="world-2",
            document_id="feedback-INV-ZENITH-2025-101",
            type="world",
            tags=["vendor:zenith-precision-engineering", "exception:price_mismatch", "decision:rejected", "source:human_feedback"],
            metadata={"invoice_number": "INV-ZENITH-2025-101", "decision": "REJECTED"},
            text="The final financial resolution set the amount to ₹0.00 because the overcharge of 8.0% exceeded the contractual limit.",
            score=0.91,
        ),
    ]


def test_duplicate_source_ids_and_sub_facts_grouping_accuracy():
    """Verify that multiple records from one review collapse into exactly 1 verified decision."""
    from agent.confidence import extract_decision_from_memory
    from agent.resolver import normalize_and_deduplicate_memories

    raw_nine = _build_mock_zenith_nine_records()
    grouped = normalize_and_deduplicate_memories(raw_nine, max_items=len(raw_nine))

    verified = [m for m in grouped if not getattr(m, "is_ungrouped", False) and not (m.document_id or "").startswith("fact-")]
    ungrouped = [m for m in grouped if getattr(m, "is_ungrouped", False) or (m.document_id or "").startswith("fact-")]

    assert len(verified) == 1, "9 raw records must collapse to exactly 1 verified decision"
    assert len(ungrouped) == 0

    primary = verified[0]
    assert primary.document_id == "feedback-INV-ZENITH-2025-101"
    assert len(primary.supporting_facts) >= 6, "Sub-facts must be grouped as supporting evidence"

    dec = extract_decision_from_memory(primary)
    assert dec is not None
    assert dec.value == "REJECTED"


def test_confidence_scoring_immune_to_duplicate_sub_facts():
    """Verify confidence formula counts each verified review document AT MOST ONCE."""
    from agent.confidence import calculate_confidence
    from data.models import ApproverDecision, ExceptionType

    raw_nine = _build_mock_zenith_nine_records()
    conf = calculate_confidence(
        proposed_decision=ApproverDecision.REJECTED,
        historical_memories=raw_nine,
        expected_vendor_slug="zenith-precision-engineering",
        expected_exception_type=ExceptionType.PRICE_MISMATCH,
    )

    # Must count n=1, NOT n=8 or n=9
    assert conf.sample_size_n == 1, f"Expected sample_size_n=1, got {conf.sample_size_n}"
    assert conf.supporting_document_ids == ["feedback-INV-ZENITH-2025-101"]
    assert conf.decision_breakdown == {"REJECTED": 1}
    assert conf.consistency == 1.0


def test_unattributed_facts_preservation_and_non_decision_status():
    """Verify unattributed facts are labeled as ungrouped and not counted as decisions."""
    from agent.confidence import calculate_confidence, extract_decision_from_memory
    from agent.resolver import normalize_and_deduplicate_memories
    from data.models import ApproverDecision
    from memory.schema import RecalledMemory

    records = [
        RecalledMemory(
            id="rev-1",
            document_id="feedback-INV-ALPHA-001",
            tags=["vendor:alpha-corp", "decision:approved"],
            metadata={"decision": "APPROVED", "invoice_number": "INV-ALPHA-001"},
            text="Alpha Corp invoice INV-ALPHA-001 approved.",
            score=0.9,
        ),
        RecalledMemory(
            id="generic-fact-1",
            document_id=None,
            tags=["policy:po_matching"],
            metadata={},
            text="General note: All POs above 10,000 INR require line-item checks.",
            score=0.6,
        ),
    ]

    grouped = normalize_and_deduplicate_memories(records, max_items=10)
    verified = [m for m in grouped if not getattr(m, "is_ungrouped", False) and not (m.document_id or "").startswith("fact-")]
    ungrouped = [m for m in grouped if getattr(m, "is_ungrouped", False) or (m.document_id or "").startswith("fact-")]

    assert len(verified) == 1
    assert len(ungrouped) == 1
    assert ungrouped[0].is_ungrouped is True

    # Confidence calculation must exclude the generic fact
    conf = calculate_confidence(
        proposed_decision=ApproverDecision.APPROVED,
        historical_memories=grouped,
        expected_vendor_slug="alpha-corp",
    )
    assert conf.sample_size_n == 1
    assert conf.supporting_document_ids == ["feedback-INV-ALPHA-001"]


def test_memory_intelligence_ui_metrics_deduplication():
    """Verify Memory Intelligence renders correct distinct counts for raw and unique decisions."""
    from unittest.mock import MagicMock, patch
    import streamlit as st
    from ui.pages.memory_intelligence import render_memory_intelligence_page

    raw_nine = _build_mock_zenith_nine_records()
    captured_metrics = {}

    def mock_metric(label, value, *args, **kwargs):
        captured_metrics[label] = value

    offline_client = MemoryClient(mode=MemoryMode.OFFLINE)
    with patch("ui.pages.memory_intelligence.get_memory_client", return_value=offline_client):
        with patch("ui.pages.memory_intelligence.recall_vendor_history", return_value=raw_nine):
            with patch("streamlit.selectbox", return_value="Zenith Precision Engineering Pvt Ltd"):
                with patch("streamlit.radio", return_value=LIVE_DEMO_BANK_ID):
                    with patch("streamlit.metric", side_effect=mock_metric):
                        render_memory_intelligence_page()

    assert captured_metrics.get("Raw Memory Records") == "9"
    assert captured_metrics.get("Unique Source Decisions") == "1"
    assert "REJECTED: 1" in str(captured_metrics.get("Historical Decision Pattern", ""))


def test_reflect_cache_bank_isolation(tmp_path: Path):
    """Verify that reflect cache isolates summaries by bank_id and prevents cross-bank leaks."""
    cache_file = tmp_path / "test_reflect_bank_isolation.json"
    cache = ReflectCache(cache_path=cache_file)

    summary_bank_a = ReflectSummary(
        vendor_slug="zenith-precision-engineering",
        summary="Bank A specific reflection summary.",
        generated_at=datetime.now(timezone.utc).isoformat(),
        bank_id="bank-a",
    )
    cache.set("zenith-precision-engineering", summary_bank_a, bank_id="bank-a")

    # In bank-a: hit
    retrieved_a = cache.get("zenith-precision-engineering", bank_id="bank-a")
    assert retrieved_a is not None
    assert retrieved_a.summary == "Bank A specific reflection summary."

    # In bank-b: miss
    retrieved_b = cache.get("zenith-precision-engineering", bank_id="bank-b")
    assert retrieved_b is None

    # In default/None bank: falls back cleanly or misses
    retrieved_none = cache.get("zenith-precision-engineering")
    assert retrieved_none is not None  # found via fallback key match


def test_reflect_cache_rejects_mock_and_placeholder_summaries(tmp_path: Path):
    """Verify that test placeholders like 'Reflect text' or 'mock' are rejected from cache."""
    cache_file = tmp_path / "test_reflect_reject.json"
    cache = ReflectCache(cache_path=cache_file)

    mock_summary = ReflectSummary(
        vendor_slug="zenith-precision-engineering",
        summary="Reflect text",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    cache.set("zenith-precision-engineering", mock_summary)

    # Must be rejected because summary is a placeholder
    assert cache.get("zenith-precision-engineering") is None
    assert cache.is_failed_summary(mock_summary) is True


def test_budget_guard_distinguishes_cloud_and_local(tmp_path: Path):
    """Verify BudgetGuard separately tracks local and cloud calls without false quota penalties."""
    log_file = tmp_path / "test_budget.jsonl"
    budget = BudgetGuard(log_path=log_file, max_reflect_calls=100)

    # Record 5 local reflect calls
    for _ in range(5):
        budget.check_and_record_reflect(bank_id="test-bank", query="zenith", mode="local")

    assert budget.local_reflect_calls == 5
    assert budget.cloud_reflect_calls == 0
    assert budget.remaining_reflect_budget == 100

    # Record 2 cloud reflect calls
    for _ in range(2):
        budget.check_and_record_reflect(bank_id="test-bank", query="zenith", mode="cloud")

    assert budget.local_reflect_calls == 5
    assert budget.cloud_reflect_calls == 2
    assert budget.remaining_reflect_budget == 98

    # Replay from log to verify persistence
    replayed = BudgetGuard(log_path=log_file, max_reflect_calls=100)
    assert replayed.local_reflect_calls == 5
    assert replayed.cloud_reflect_calls == 2
    assert replayed.remaining_reflect_budget == 98


def test_reflect_cache_hit_bypasses_budget_guard(tmp_path: Path):
    """Verify that reading a cached reflection never invokes the budget guard or API client."""
    cache_file = tmp_path / "test_cache_hit.json"
    log_file = tmp_path / "test_budget.jsonl"
    cache = ReflectCache(cache_path=cache_file)
    budget = BudgetGuard(log_path=log_file, max_reflect_calls=100)

    valid_summary = ReflectSummary(
        vendor_slug="apex-precision-tools",
        summary="Apex has consistently met payment criteria and PO terms.",
        generated_at=datetime.now(timezone.utc).isoformat(),
        bank_id=LIVE_DEMO_BANK_ID,
    )
    cache.set("apex-precision-tools", valid_summary, bank_id=LIVE_DEMO_BANK_ID)

    mock_sdk = MagicMock()
    client = MemoryClient(
        mode=MemoryMode.LOCAL,
        reflect_cache=cache,
        budget_guard=budget,
    )
    client._sdk_client = mock_sdk

    prof = client.reflect(LIVE_DEMO_BANK_ID, "apex-precision-tools")
    assert prof.is_error is False
    assert prof.summary == valid_summary.summary
    assert mock_sdk.reflect.call_count == 0
    assert budget.local_reflect_calls == 0
    assert budget.cloud_reflect_calls == 0

