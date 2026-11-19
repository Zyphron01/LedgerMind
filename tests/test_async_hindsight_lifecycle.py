"""
tests/test_async_hindsight_lifecycle.py
────────────────────────────────────────────────────────────────────────────────
Regression tests for MemoryClient async lifecycle, event-loop ownership,
cross-thread Streamlit rerun safety, and aiohttp ClientSession isolation.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import threading
from unittest.mock import MagicMock, patch
import pytest

from hindsight_client_api.models.recall_response import RecallResponse
from hindsight_client_api.models.recall_result import RecallResult
from memory.budget_guard import BudgetGuard
from memory.client import MemoryClient
from memory.reflect_cache import ReflectCache
from memory.schema import MemoryMode, ReflectSummary


def test_memory_client_initialization_modes():
    """Verify MemoryClient properly sets up endpoints and modes."""
    local_client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    assert local_client.mode == MemoryMode.LOCAL
    assert local_client.base_url == "http://localhost:8888"

    offline_client = MemoryClient(mode=MemoryMode.OFFLINE)
    assert offline_client.mode == MemoryMode.OFFLINE
    assert offline_client.base_url == "offline://local"


def test_repeated_recalls_same_thread():
    """Verify repeated recalls on the same thread maintain clean lifecycle."""
    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    mock_sdk = MagicMock()
    mock_resp = RecallResponse(results=[])
    mock_sdk.recall.return_value = mock_resp
    client._sdk_client = mock_sdk

    res1 = client.recall(bank_id="test-bank", query="query 1")
    assert res1 == []
    assert client.last_recall_source == "hindsight"

    res2 = client.recall(bank_id="test-bank", query="query 2")
    assert res2 == []
    assert client.last_recall_source == "hindsight"
    assert mock_sdk.recall.call_count == 2


def test_cross_thread_recalls_simulate_streamlit_reruns():
    """
    Verify that sequential calls across distinct worker threads (simulating
    Streamlit rerun threads) do NOT raise:
    RuntimeError: Timeout context manager should be used inside a task.
    """
    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")

    errors = []
    results = []

    def run_in_thread(thread_id: int):
        try:
            # We patch Hindsight to simulate real SDK instances created per thread
            mock_resp = RecallResponse(results=[
                RecallResult(
                    id=f"doc-{thread_id}",
                    text=f"Memory from thread {thread_id}",
                    tags=[f"tag-{thread_id}"],
                )
            ])
            with patch("memory.client.Hindsight") as mock_hindsight_cls:
                mock_inst = MagicMock()
                mock_inst.recall.return_value = mock_resp
                mock_hindsight_cls.return_value = mock_inst

                recalled = client.recall(bank_id="test-bank", query=f"thread {thread_id}")
                results.append(len(recalled))
                # Verify that client.close() was executed in finally
                mock_inst.close.assert_called_once()
        except Exception as e:
            errors.append((thread_id, type(e).__name__, str(e)))

    # Launch across 3 distinct sequential worker threads
    for t_id in range(3):
        t = threading.Thread(target=run_in_thread, args=(t_id,))
        t.start()
        t.join()

    assert errors == [], f"Cross-thread recall raised errors: {errors}"
    assert results == [1, 1, 1]


def test_list_memories_lifecycle_safety():
    """Verify list_memories properly manages SDK lifecycle across calls."""
    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    with patch("memory.client.Hindsight") as mock_hindsight_cls:
        mock_inst = MagicMock()
        mock_inst.list_memories.return_value = MagicMock(items=[MagicMock(document_id="doc-1")])
        mock_hindsight_cls.return_value = mock_inst

        mems = client.list_memories(bank_id="test-bank")
        assert mems is not None
        mock_inst.list_memories.assert_called_once_with(bank_id="test-bank")
        mock_inst.close.assert_called_once()


def test_offline_fallback_on_sdk_exception():
    """Verify clean fallback to offline store when SDK raises connection error."""
    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    mock_sdk = MagicMock()
    mock_sdk.recall.side_effect = RuntimeError("Connection refused")
    client._sdk_client = mock_sdk

    results = client.recall(bank_id="ledgermind-live-demo", query="Zenith Precision")
    assert client.last_recall_source == "offline"
    assert "RuntimeError" in (client.last_fallback_reason or "")
    # Should successfully find Zenith in offline fallback store
    zenith = next((m for m in results if m.document_id == "feedback-INV-ZENITH-2025-101"), None)
    assert zenith is not None
    assert zenith.is_offline_fallback is True


def test_reflect_summary_backward_compatibility():
    """Verify ReflectSummary safely handles missing is_error without AttributeError."""
    prof = ReflectSummary(vendor_slug="test-vendor", summary="Summary text")
    if "is_error" in prof.__dict__:
        del prof.__dict__["is_error"]
    assert prof.is_error is False
    assert getattr(prof, "is_error", False) is False


def test_recall_when_event_loop_is_already_running():
    """
    Verify that calling MemoryClient.recall() from inside an active running event loop
    does NOT raise 'RuntimeError: This event loop is already running' or unawaited coroutine warnings.
    """
    import warnings
    from hindsight_client_api.models.recall_response import RecallResponse
    from hindsight_client_api.models.recall_result import RecallResult

    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    mock_resp = RecallResponse(results=[
        RecallResult(id="doc-1", text="Sample memory", tags=["tag1"])
    ])

    with patch("memory.client.Hindsight") as mock_hindsight_cls:
        mock_inst = MagicMock()
        mock_inst.recall.return_value = mock_resp
        mock_hindsight_cls.return_value = mock_inst

        async def _inside_running_loop():
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                recalled = client.recall(bank_id="test-bank", query="test query")
                # Assert no coroutine unawaited warnings
                coro_warnings = [
                    w for w in caught
                    if issubclass(w.category, RuntimeWarning) and "coroutine" in str(w.message).lower()
                ]
                assert len(coro_warnings) == 0, f"Unawaited coroutine warnings: {[str(w.message) for w in coro_warnings]}"
                assert len(recalled) == 1
                assert recalled[0].id == "doc-1"

        asyncio.run(_inside_running_loop())


def test_repeated_recalls_and_page_switching_across_threads():
    """
    Simulate user switching between Streamlit pages (Queue -> Workbench -> Memory Intelligence)
    across distinct worker threads, verifying no event loop collision or session corruption.
    """
    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    pages = ["Overview", "Queue", "Workbench", "Memory Intelligence"]
    results_by_page = {}
    thread_errors = []

    mock_resp = RecallResponse(results=[
        RecallResult(id="doc-common", text="Precedent memory", tags=["precedent"])
    ])

    with patch("memory.client.Hindsight") as mock_hindsight_cls:
        mock_inst = MagicMock()
        mock_inst.recall.return_value = mock_resp
        mock_hindsight_cls.return_value = mock_inst

        def _simulate_page_render(page_name: str):
            try:
                # Query memory as page renders
                mems = client.recall(bank_id="test-bank", query=f"Query for {page_name}")
                results_by_page[page_name] = len(mems)
            except Exception as e:
                thread_errors.append((page_name, type(e).__name__, str(e)))

        threads = []
        for p in pages:
            t = threading.Thread(target=_simulate_page_render, args=(p,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5.0)

    assert thread_errors == [], f"Thread errors during page switching: {thread_errors}"
    assert all(results_by_page[p] == 1 for p in pages)


def test_async_cleanup_no_unawaited_coroutine_warnings(tmp_path: Path):
    """
    Verify that calling retain, recall, reflect, list_memories and close
    does NOT emit RuntimeWarning: coroutine was never awaited.
    Uses isolated cache and budget log to prevent disk pollution.
    """
    import warnings
    from hindsight_client_api.models.reflect_response import ReflectResponse

    test_cache = ReflectCache(cache_path=tmp_path / "test_reflect.json")
    test_budget = BudgetGuard(log_path=tmp_path / "test_budget.jsonl")

    client = MemoryClient(
        mode=MemoryMode.LOCAL,
        base_url="http://localhost:8888",
        reflect_cache=test_cache,
        budget_guard=test_budget,
    )
    with patch("memory.client.Hindsight") as mock_hindsight_cls:
        mock_inst = MagicMock()
        mock_inst.recall.return_value = RecallResponse(results=[])
        mock_inst.reflect.return_value = MagicMock(text="Vendor demonstrates consistent quality.")
        mock_inst.list_memories.return_value = MagicMock(items=[])
        mock_hindsight_cls.return_value = mock_inst

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client.recall(bank_id="test-bank", query="query")
            client.reflect(bank_id="test-bank", vendor_slug="zenith-precision-engineering")
            client.list_memories(bank_id="test-bank")
            client.close()

            coro_warnings = [
                w for w in caught
                if issubclass(w.category, RuntimeWarning) and "coroutine" in str(w.message).lower()
            ]
            assert len(coro_warnings) == 0, f"Unawaited coroutines detected: {[str(w.message) for w in coro_warnings]}"


def test_live_local_hindsight_read_only_recall_and_grouping():
    """
    Bounded live test against local Hindsight container (http://localhost:8888)
    without consuming paid credits or performing bulk/write operations.
    Verifies 9 raw records are retrieved and grouped cleanly into 1 verified decision.
    """
    import requests
    from agent.resolver import normalize_and_deduplicate_memories
    from config import LIVE_DEMO_BANK_ID
    from memory.operations import recall_vendor_history

    # Fast connectivity probe to verify container is active
    try:
        r = requests.get("http://localhost:8888/health", timeout=1.0)
        container_active = (r.status_code == 200)
    except Exception:
        container_active = False

    if not container_active:
        pytest.skip("Local Hindsight container on http://localhost:8888 is not reachable")

    client = MemoryClient(mode=MemoryMode.LOCAL, base_url="http://localhost:8888")
    results = recall_vendor_history(
        client=client,
        bank_id=LIVE_DEMO_BANK_ID,
        vendor_name="Zenith Precision Engineering Pvt Ltd",
        vendor_slug="zenith-precision-engineering",
        limit=15,
    )

    assert client.last_recall_source == "hindsight"
    assert len(results) == 9, f"Expected 9 raw Hindsight records for Zenith, got {len(results)}"

    # Grouping verification
    grouped = normalize_and_deduplicate_memories(results, max_items=len(results))
    verified = [m for m in grouped if not getattr(m, "is_ungrouped", False) and not (m.document_id or "").startswith("fact-")]
    assert len(verified) == 1
    assert verified[0].document_id == "feedback-INV-ZENITH-2025-101"
    assert len(verified[0].supporting_facts) >= 6
