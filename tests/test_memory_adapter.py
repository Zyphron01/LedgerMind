"""
tests/test_memory_adapter.py
────────────────────────────────────────────────────────────────────────────────
Unit tests for LedgerMind Memory Adapter:
  - RecalledMemory normalization
  - MemoryClient in Local, Cloud, and Offline modes
  - BudgetGuard enforcement and logging
  - OfflineStore persistence and lexical search
  - ReflectCache disk persistence, freshness, and invalidation
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from memory.budget_guard import BudgetGuard, BudgetExceededError
from memory.client import MemoryClient
from memory.offline_store import OfflineStore
from memory.reflect_cache import ReflectCache
from memory.schema import MemoryMode, RecalledMemory, ReflectSummary


def test_recalled_memory_normalization():
    """Verify RecalledMemory properly normalizes raw SDK fields and generates citations."""
    raw_mock_result = type("MockRecallResult", (), {
        "id": "mem-12345",
        "text": "Invoice INV-001 had a price mismatch of 3% which was approved.",
        "type": "observation",
        "document_id": "decision-INV-001",
        "tags": ["vendor:prabhav", "exception:price_mismatch"],
        "metadata": {"decision": "APPROVED", "vendor_name": "Prabhav Infosystems"},
        "scores": type("MockScores", (), {
            "final": 0.88,
            "semantic": 0.85,
            "reranker": 0.90,
            "keyword": 0.75,
        })(),
        "occurred_start": datetime(2025, 3, 14, 11, 0, tzinfo=timezone.utc),
        "occurred_end": None,
    })()

    mem = RecalledMemory.from_recall_result(raw_mock_result)

    assert mem.id == "mem-12345"
    assert mem.document_id == "decision-INV-001"
    assert mem.score == 0.88
    assert mem.metadata["decision"] == "APPROVED"
    assert not mem.is_offline_fallback

    citation = mem.to_citation_summary()
    assert "decision-INV-001" in citation
    assert "2025-03-14" in citation
    assert "0.88" in citation


def test_budget_guard_local_vs_cloud(tmp_path: Path):
    """
    BudgetGuard must log usage without blocking in LOCAL mode,
    but MUST raise BudgetExceededError when caps are exceeded in CLOUD mode.
    """
    log_file = tmp_path / "test_budget.jsonl"
    guard = BudgetGuard(log_path=log_file, max_retain_tokens=200, max_reflect_calls=1)

    # 1. Local mode: exceeding limit logs but DOES NOT raise
    est = guard.check_and_record_retain("test-bank", "Short text", mode="local")
    assert est > 0
    # Retain huge text in local mode
    guard.check_and_record_retain("test-bank", "X" * 2000, mode="local")
    # No exception in local mode

    # 2. Cloud mode: exceeding limit MUST raise BudgetExceededError
    with pytest.raises(BudgetExceededError, match="Cloud budget guard refused retain"):
        guard.check_and_record_retain("test-bank", "Y" * 1000, mode="cloud")

    # 3. Cloud reflect: call 1 succeeds, call 2 fails
    guard.check_and_record_reflect("test-bank", "query 1", mode="cloud")
    with pytest.raises(BudgetExceededError, match="Cloud budget guard refused reflect"):
        guard.check_and_record_reflect("test-bank", "query 2", mode="cloud")

    # Verify log persistence
    assert log_file.exists()
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) >= 4


def test_offline_store_retention_and_lexical_recall(tmp_path: Path):
    """OfflineStore must persist records and provide keyword/tag matching with offline labels."""
    store_file = tmp_path / "offline_test.jsonl"
    store = OfflineStore(store_path=store_file)

    rec_id = store.retain(
        bank_id="bank-off",
        content="Devanshi Logistics suffered transit damage causing quantity shortfall of 5 units.",
        document_id="decision-INV-DL-101",
        tags=["vendor:devanshi", "exception:quantity_shortfall"],
        metadata={"decision": "APPROVED", "vendor_name": "Devanshi Logistics"},
    )
    assert rec_id.startswith("off-")

    # Recall matching tag and keyword
    results = store.recall(
        bank_id="bank-off",
        query="transit damage quantity shortfall",
        tags=["vendor:devanshi"],
        limit=5,
    )
    assert len(results) == 1
    assert results[0].document_id == "decision-INV-DL-101"
    assert results[0].is_offline_fallback is True
    assert results[0].score is not None

    # Recall non-matching tag should return empty
    empty_res = store.recall(
        bank_id="bank-off",
        query="transit damage",
        tags=["vendor:unrelated"],
    )
    assert len(empty_res) == 0


def test_reflect_cache_lifecycle(tmp_path: Path):
    """ReflectCache must persist to disk, verify freshness, and support targeted invalidation."""
    cache_file = tmp_path / "test_reflect.json"
    cache = ReflectCache(cache_path=cache_file)

    slug = "prabhav-infosystems"
    summary_text = "Vendor tends to have 2-4% rate creep which is edited to PO rate."

    assert cache.get(slug) is None
    assert not cache.is_fresh(slug)

    # Set profile
    summary = cache.set(slug, summary_text)
    assert summary.vendor_slug == slug
    assert not summary.cached

    # Retrieve cached
    cached = cache.get(slug)
    assert cached is not None
    assert cached.cached is True
    assert cached.summary == summary_text
    assert cache.is_fresh(slug, max_age_hours=24)

    # Invalidate single vendor
    count = cache.invalidate(slug)
    assert count == 1
    assert cache.get(slug) is None


def test_memory_client_offline_mode(tmp_path: Path):
    """MemoryClient initialized in OFFLINE mode must route to offline store without network calls."""
    store_file = tmp_path / "offline_client_test.jsonl"
    offline_store = OfflineStore(store_path=store_file)

    client = MemoryClient(
        mode=MemoryMode.OFFLINE,
        offline_store=offline_store,
    )
    assert client.mode == MemoryMode.OFFLINE

    doc_id = client.retain(
        bank_id="bank-1",
        content="Kamalnath duplicate invoice submission rejected outright.",
        document_id="decision-INV-KS-001",
        tags=["vendor:kamalnath", "exception:duplicate_invoice"],
    )
    assert doc_id == "decision-INV-KS-001"

    mems = client.recall(
        bank_id="bank-1",
        query="duplicate invoice rejected",
        tags=["vendor:kamalnath"],
    )
    assert len(mems) == 1
    assert mems[0].is_offline_fallback is True

    client.close()

