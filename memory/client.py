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

from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

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

        # Initialize Hindsight SDK if not offline
        self._sdk_client: Optional[Hindsight] = None
        if self.mode in (MemoryMode.LOCAL, MemoryMode.CLOUD):
            try:
                self._sdk_client = Hindsight(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    timeout=self.recall_timeout,
                )
            except Exception as e:
                print(f"⚠️  Warning: Failed to initialize Hindsight SDK ({e}); falling back to offline.")
                self.mode = MemoryMode.OFFLINE

    def is_healthy(self) -> bool:
        """Fast connectivity check for diagnostics and sidebar status polling."""
        if getattr(self, "configured_mode", self.mode) == MemoryMode.OFFLINE or not self.base_url or self.base_url.startswith("offline://"):
            return False
        try:
            import requests
            resp = requests.get(f"{self.base_url.rstrip('/')}/health", timeout=5.0)
            is_ok = resp.status_code == 200
            if is_ok:
                if self._sdk_client is None and getattr(self, "configured_mode", self.mode) in (MemoryMode.LOCAL, MemoryMode.CLOUD):
                    try:
                        self._sdk_client = Hindsight(
                            base_url=self.base_url,
                            api_key=self.api_key,
                            timeout=self.recall_timeout,
                        )
                    except Exception:
                        pass
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

        if self.mode == MemoryMode.OFFLINE or not self._sdk_client:
            return document_id or "offline-retained"

        # Check and record budget
        self.budget_guard.check_and_record_retain(
            bank_id=bank_id,
            content=content,
            mode=self.mode.value,
        )

        # Call Hindsight SDK
        safe_meta = {k: str(v) for k, v in (metadata or {}).items()}
        try:
            resp = self._sdk_client.retain(
                bank_id=bank_id,
                content=content,
                timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
                context=context,
                document_id=document_id,
                tags=tags or [],
                metadata=safe_meta,
                retain_async=False,
            )
            return document_id or str(getattr(resp, "id", "retained"))
        except Exception as e:
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
        if self.mode == MemoryMode.OFFLINE or not self._sdk_client:
            self.last_recall_source = "offline"
            self.last_fallback_reason = "Offline mode configured" if self.mode == MemoryMode.OFFLINE else "SDK client unavailable"
            self.last_recall_elapsed = time.perf_counter() - t_start
            offline_results = self.offline_store.recall(bank_id=bank_id, query=query, tags=tags, limit=limit)
            for m in offline_results:
                m.bank_id = bank_id
                m.is_offline_fallback = True
            return offline_results

        try:
            # Query Hindsight SDK with bounded timeout
            kwargs: Dict[str, Any] = {
                "bank_id": bank_id,
                "query": query,
            }
            if tags:
                kwargs["tags"] = tags
            if min_score is not None:
                kwargs["min_scores"] = {"final": min_score}

            sdk_resp: RecallResponse = self._sdk_client.recall(**kwargs)
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

        # Check cache first
        if not force_refresh:
            cached = self.reflect_cache.get(slug)
            if cached and self.reflect_cache.is_fresh(slug):
                return cached

        default_query = (
            f"Synthesize historical AP exception patterns, recurring discrepancies, "
            f"and approved resolution guidelines for vendor {slug}."
        )
        actual_query = query or default_query

        if self.mode == MemoryMode.OFFLINE or not self._sdk_client:
            summary = (
                f"[OFFLINE PROFILE] Vendor {slug}: Synthesized profile unavailable in offline mode. "
                f"Referencing individual recalled records."
            )
            return self.reflect_cache.set(slug, summary)

        # Check and record budget
        self.budget_guard.check_and_record_reflect(
            bank_id=bank_id,
            query=actual_query,
            mode=self.mode.value,
        )

        try:
            # Call Hindsight reflect with vendor scoping
            tags = [f"vendor:{slug}"]
            resp: ReflectResponse = self._sdk_client.reflect(
                bank_id=bank_id,
                query=actual_query,
                tags=tags,
            )
            text_content = getattr(resp, "text", "") or getattr(resp, "content", "") or str(resp)
            return self.reflect_cache.set(slug, text_content)

        except Exception as e:
            fallback_text = f"Reflect generation failed ({e}); falling back to direct historical recall."
            return self.reflect_cache.set(slug, fallback_text)

    def close(self) -> None:
        """Cleanly close underlying SDK connection sessions."""
        if self._sdk_client:
            try:
                self._sdk_client.close()
            except Exception:
                pass
            self._sdk_client = None
