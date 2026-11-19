"""
memory/client.py
────────────────────────────────────────────────────────────────────────────────
Unified Memory Client for LedgerMind.

Connects to:
  - Local Hindsight container (http://localhost:8888)
  - Hindsight Cloud API (https://api.hindsight.vectorize.io)
  - Offline local JSONL fallback store

Wraps Hindsight SDK, Budget Guard, and Offline Store behind a clean,
deterministic interface with normalized response models.
"""

import asyncio
import concurrent.futures
from datetime import datetime, timezone
import inspect
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from hindsight_client import Hindsight
from hindsight_client_api.models.recall_response import RecallResponse
from hindsight_client_api.models.recall_result import RecallResult
from hindsight_client_api.models.reflect_response import ReflectResponse

from memory.budget_guard import BudgetGuard
from memory.offline_store import OfflineStore
from memory.reflect_cache import ReflectCache
from memory.schema import MemoryMode, RecalledMemory, ReflectSummary


class MemoryClient:
    """Thread-safe unified client for Hindsight and offline AP memory operations."""

    def __init__(
        self,
        mode: Optional[MemoryMode] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        budget_guard: Optional[BudgetGuard] = None,
        offline_store: Optional[OfflineStore] = None,
        reflect_cache: Optional[ReflectCache] = None,
    ) -> None:
        # Determine mode
        if mode is not None:
            self.mode = mode
        else:
            env_mode = os.getenv("HINDSIGHT_MODE", "local").lower()
            self.mode = MemoryMode(env_mode) if env_mode in ("local", "cloud", "offline") else MemoryMode.LOCAL

        # Determine URL & credentials
        if self.mode == MemoryMode.LOCAL:
            self.base_url = base_url or os.getenv("HINDSIGHT_LOCAL_URL", "http://localhost:8888")
            self.api_key = api_key or os.getenv("HINDSIGHT_API_KEY", "") or None
        elif self.mode == MemoryMode.CLOUD:
            self.base_url = base_url or os.getenv("HINDSIGHT_CLOUD_URL", "https://api.hindsight.vectorize.io")
            self.api_key = api_key or os.getenv("HINDSIGHT_API_KEY", "")
        else:
            self.base_url = "offline://local"
            self.api_key = None

        self.budget_guard = budget_guard or BudgetGuard()
        self.offline_store = offline_store or OfflineStore()
        self.reflect_cache = reflect_cache or ReflectCache()
        self.configured_mode = self.mode

        # Bounded recall timeout (default: 30.0s to accommodate 4-7s server vector search time)
        timeout_env = os.getenv("HINDSIGHT_RECALL_TIMEOUT", "30.0")
        try:
            self.recall_timeout = float(timeout_env)
        except ValueError:
            self.recall_timeout = 30.0

        self.last_recall_source: str = "offline" if self.mode == MemoryMode.OFFLINE else "hindsight"
        self.last_fallback_reason: Optional[str] = None
        self.last_recall_elapsed: Optional[float] = None
        self.last_retain_status: str = "NOT_ATTEMPTED"
        self.last_retain_error: Optional[str] = None

        # SDK client lifecycle management (prevents cross-loop / cross-thread aiohttp corruption)
        self._manual_sdk_client: Optional[Hindsight] = None
        self._explicitly_disabled: bool = False
        self._executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="lm-memory-worker"
        )

    def _execute_sdk_operation(self, op_name: str, *args, **kwargs) -> Any:
        """
        Execute an SDK operation through an explicit, loop-safe sync-to-async boundary.
        Guarantees:
          - Native async SDK methods (arecall, areflect, aretain, alist_memories) are awaited properly.
          - Session cleanup (aclose) is executed on the exact same loop.
          - Works safely whether called from a synchronous thread or an active event loop.
          - Supports both live Hindsight instances and mocked test clients.
        """
        sdk = self._get_active_sdk_client()
        if not sdk:
            raise RuntimeError("Hindsight SDK client unavailable")

        # Handle mocked test clients (e.g. MagicMock in unit tests)
        is_mock = isinstance(sdk, MagicMock) or hasattr(sdk, "_mock_return_value") or not hasattr(sdk, f"a{op_name}")
        if is_mock:
            try:
                fn = getattr(sdk, op_name)
                res = fn(*args, **kwargs)
                if inspect.iscoroutine(res):
                    return asyncio.run(res)
                return res
            finally:
                if sdk is not self._manual_sdk_client:
                    if hasattr(sdk, "close"):
                        try:
                            c = sdk.close()
                            if inspect.iscoroutine(c):
                                asyncio.run(c)
                        except Exception:
                            pass

        # For real live Hindsight SDK instances:
        # Execute the native async method (arecall, areflect, aretain, alist_memories)
        # and its async cleanup (aclose) on an isolated worker thread event loop.
        async def _async_worker():
            try:
                async_fn = getattr(sdk, f"a{op_name}")
                return await async_fn(*args, **kwargs)
            finally:
                try:
                    await sdk.aclose()
                except Exception:
                    pass

        future = self._executor.submit(asyncio.run, _async_worker())
        return future.result(timeout=self.recall_timeout + 5.0)

    def _create_sdk_client(self) -> Optional[Hindsight]:
        """Instantiate a clean Hindsight SDK client with bounded timeout."""
        if self.mode not in (MemoryMode.LOCAL, MemoryMode.CLOUD) or not self.base_url or self.base_url.startswith("offline://"):
            return None
        try:
            return Hindsight(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.recall_timeout,
            )
        except Exception as e:
            print(f"⚠️  Warning: Failed to instantiate Hindsight SDK client ({e})")
            return None

    def _get_active_sdk_client(self) -> Optional[Hindsight]:
        """
        Return an active SDK client guaranteed to be valid for the current thread and event loop.
        Prioritizes any explicitly injected mock client (for testing).
        """
        if self._manual_sdk_client is not None:
            return self._manual_sdk_client
        if self._explicitly_disabled:
            return None
        return self._create_sdk_client()

    @property
    def _sdk_client(self) -> Optional[Hindsight]:
        """Backward-compatible property for SDK client access."""
        return self._get_active_sdk_client()

    @_sdk_client.setter
    def _sdk_client(self, value: Optional[Hindsight]) -> None:
        self._manual_sdk_client = value
        self._explicitly_disabled = (value is None)

    def is_healthy(self) -> bool:
        """Fast connectivity check for diagnostics and sidebar status polling."""
        if getattr(self, "configured_mode", self.mode) == MemoryMode.OFFLINE or not self.base_url or self.base_url.startswith("offline://"):
            return False
        try:
            import requests
            resp = requests.get(f"{self.base_url.rstrip('/')}/health", timeout=5.0)
            is_ok = resp.status_code == 200
            if is_ok:
                self.mode = self.configured_mode
            return is_ok
        except Exception:
            return False

    def retain(
        self,
        bank_id: str,
        content: str,
        timestamp: Optional[str] = None,
        document_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None,
        context: Optional[str] = "accounts-payable exception resolution",
    ) -> str:
        """
        Retain memory record into active memory backend.
        Checks budget in cloud mode, calls Hindsight SDK or offline store,
        and returns document_id.
        """
        # Always record in offline store as an immutable local audit log
        self.offline_store.retain(
            bank_id=bank_id,
            content=content,
            timestamp=timestamp,
            document_id=document_id,
            tags=tags,
            metadata=metadata,
            context=context,
        )

        if getattr(self, "configured_mode", self.mode) == MemoryMode.OFFLINE:
            self.last_retain_status = "NOT_ATTEMPTED"
            self.last_retain_error = None
            return document_id or "offline-retained"

        sdk = self._get_active_sdk_client()
        if self.mode == MemoryMode.OFFLINE or not sdk:
            self.last_retain_status = "PENDING_SYNC"
            self.last_retain_error = "Hindsight service unavailable; queued for sync"
            return document_id or "offline-retained"

        # Check and record budget
        self.budget_guard.check_and_record_retain(
            bank_id=bank_id,
            content=content,
            mode=self.mode.value,
        )

        # Call Hindsight SDK via loop-safe executor
        safe_meta = {k: str(v) for k, v in (metadata or {}).items()}
        try:
            resp = self._execute_sdk_operation(
                "retain",
                bank_id=bank_id,
                content=content,
                timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
                context=context,
                document_id=document_id,
                tags=tags or [],
                metadata=safe_meta,
                retain_async=False,
            )
            self.last_retain_status = "SYNCED"
            self.last_retain_error = None
            return document_id or str(getattr(resp, "id", "retained"))
        except Exception as e:
            self.last_retain_status = "FAILED"
            self.last_retain_error = str(e)
            print(f"⚠️  Hindsight retain service warning ({e}); safely recorded in offline audit store.")
            return document_id or "offline-retained"

    def recall(
        self,
        bank_id: str,
        query: str,
        tags: Optional[List[str]] = None,
        limit: int = 5,
        min_score: Optional[float] = None,
    ) -> List[RecalledMemory]:
        """
        Recall relevant historical memories.
        In offline mode, falls back to lexical/tag filtering.
        """
        t_start = time.perf_counter()
        sdk = self._get_active_sdk_client()
        if self.mode == MemoryMode.OFFLINE or not sdk:
            self.last_recall_source = "offline"
            self.last_fallback_reason = "Offline mode configured" if self.mode == MemoryMode.OFFLINE else "SDK client unavailable"
            self.last_recall_elapsed = time.perf_counter() - t_start
            offline_results = self.offline_store.recall(bank_id=bank_id, query=query, tags=tags, limit=limit)
            for m in offline_results:
                m.bank_id = bank_id
                m.is_offline_fallback = True
            return offline_results

        try:
            # Query Hindsight SDK with bounded timeout via loop-safe executor
            kwargs: Dict[str, Any] = {
                "bank_id": bank_id,
                "query": query,
            }
            if tags:
                kwargs["tags"] = tags
            if min_score is not None:
                kwargs["min_scores"] = {"final": min_score}

            sdk_resp: RecallResponse = self._execute_sdk_operation("recall", **kwargs)
            elapsed = time.perf_counter() - t_start
            self.last_recall_elapsed = elapsed
            self.last_recall_source = "hindsight"
            self.last_fallback_reason = None

            results: List[RecalledMemory] = []
            if sdk_resp and hasattr(sdk_resp, "results") and sdk_resp.results:
                for item in sdk_resp.results:
                    mem = RecalledMemory.from_recall_result(item)
                    mem.bank_id = bank_id
                    mem.is_offline_fallback = False
                    results.append(mem)
            return results[:limit]

        except Exception as e:
            elapsed = time.perf_counter() - t_start
            self.last_recall_elapsed = elapsed
            self.last_recall_source = "offline"
            self.last_fallback_reason = f"{type(e).__name__} after {elapsed:.3f}s: {e}"
            print(f"⚠️  Hindsight recall error after {elapsed:.3f}s ({type(e).__name__}: {e}); falling back to offline store.")
            offline_results = self.offline_store.recall(bank_id=bank_id, query=query, tags=tags, limit=limit)
            for m in offline_results:
                m.bank_id = bank_id
                m.is_offline_fallback = True
            return offline_results

    def reflect(
        self,
        bank_id: str,
        vendor_slug: str,
        query: Optional[str] = None,
        force_refresh: bool = False,
    ) -> ReflectSummary:
        """
        Retrieve vendor-level synthesized profile.
        Uses disk cache unless force_refresh=True or cache miss.
        """
        slug = vendor_slug.strip().lower()

        # Check cache first (scoped by bank_id and vendor_slug)
        if not force_refresh:
            cached = self.reflect_cache.get(slug, bank_id=bank_id)
            if (
                cached
                and not getattr(cached, "is_error", False)
                and not self.reflect_cache.is_failed_summary(getattr(cached, "summary", ""))
                and self.reflect_cache.is_fresh(slug, bank_id=bank_id)
            ):
                return cached

        default_query = (
            f"Synthesize historical AP exception patterns, recurring discrepancies, "
            f"and approved resolution guidelines for vendor {slug}."
        )
        actual_query = query or default_query

        sdk = self._get_active_sdk_client()
        if self.mode == MemoryMode.OFFLINE or not sdk:
            summary = (
                f"[OFFLINE PROFILE] Vendor {slug}: Synthesized profile unavailable in offline mode. "
                f"Referencing individual recalled records."
            )
            return ReflectSummary(
                vendor_slug=slug,
                summary=summary,
                generated_at=datetime.now(timezone.utc),
                cached=False,
                is_error=False,
                bank_id=bank_id,
            )

        # Check and record budget
        self.budget_guard.check_and_record_reflect(
            bank_id=bank_id,
            query=actual_query,
            mode=self.mode.value,
        )

        try:
            # Call Hindsight reflect with vendor scoping via loop-safe executor
            tags = [f"vendor:{slug}"]
            resp: ReflectResponse = self._execute_sdk_operation(
                "reflect",
                bank_id=bank_id,
                query=actual_query,
                tags=tags,
            )
            text_content = getattr(resp, "text", "") or getattr(resp, "content", "") or str(resp)
            if self.reflect_cache.is_failed_summary(text_content):
                return ReflectSummary(
                    vendor_slug=slug,
                    summary=text_content,
                    generated_at=datetime.now(timezone.utc),
                    cached=False,
                    is_error=True,
                    error_message=text_content,
                    bank_id=bank_id,
                )
            return self.reflect_cache.set(slug, text_content, bank_id=bank_id)

        except Exception as e:
            err_type = type(e).__name__
            err_msg = str(e).strip()
            err_details = f"{err_type}: {err_msg}" if err_msg else err_type
            return ReflectSummary(
                vendor_slug=slug,
                summary=f"Reflect synthesis unavailable ({err_details}). Using direct historical recall.",
                generated_at=datetime.now(timezone.utc),
                cached=False,
                is_error=True,
                error_message=err_details,
                bank_id=bank_id,
            )

    def list_memories(self, bank_id: str) -> Any:
        """Query live memories for a bank with loop-safe SDK client lifecycle."""
        if not self._get_active_sdk_client() or self.mode == MemoryMode.OFFLINE:
            return None
        try:
            return self._execute_sdk_operation("list_memories", bank_id=bank_id)
        except Exception as e:
            print(f"⚠️  Hindsight list_memories warning ({e})")
            return None

    def close(self) -> None:
        """Cleanly close underlying SDK connection sessions and executor."""
        if hasattr(self, "_executor") and self._executor is not None:
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass
        if self._manual_sdk_client:
            try:
                self._manual_sdk_client.close()
            except Exception:
                pass
            self._manual_sdk_client = None
