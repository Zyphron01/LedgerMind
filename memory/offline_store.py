"""
memory/offline_store.py
────────────────────────────────────────────────────────────────────────────────
Persistent Offline Fallback Store for LedgerMind.

Appends retained memories to a local JSONL file (offline_memory.jsonl) and provides
deterministic lexical/tag-based retrieval when running in OFFLINE mode or when
Hindsight services are unreachable.

IMPORTANT: Offline mode is explicitly flagged as a keyword fallback and is NOT
equivalent to Hindsight semantic retrieval.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from memory.schema import RecalledMemory

ROOT_DIR = Path(__file__).resolve().parent.parent
OFFLINE_STORE_FILE = ROOT_DIR / "offline_memory.jsonl"


class OfflineStore:
    """Manages persistent offline memory storage in JSON Lines format."""

    def __init__(self, store_path: Path = OFFLINE_STORE_FILE) -> None:
        self.store_path = Path(store_path)

    def retain(
        self,
        bank_id: str,
        content: str,
        timestamp: Optional[str] = None,
        document_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        context: Optional[str] = None,
    ) -> str:
        """
        Store memory record to local offline JSONL file with idempotent upsert.
        If a record with matching (bank_id, document_id) exists, updates it in place
        to prevent cross-test duplication and file bloat.
        """
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        rec_id = f"off-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        record = {
            "id": rec_id,
            "bank_id": bank_id,
            "content": content,
            "timestamp": timestamp or now_iso,
            "document_id": document_id,
            "tags": tags or [],
            "metadata": metadata or {},
            "context": context,
            "created_at": now_iso,
        }

        # Idempotent upsert by (bank_id, document_id)
        if document_id and self.store_path.exists():
            lines: List[str] = []
            replaced = False
            with open(self.store_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        existing = json.loads(stripped)
                        if existing.get("bank_id") == bank_id and existing.get("document_id") == document_id:
                            # Preserve initial record ID and created_at timestamp
                            record["id"] = existing.get("id", rec_id)
                            record["created_at"] = existing.get("created_at", now_iso)
                            lines.append(json.dumps(record, default=str))
                            replaced = True
                            continue
                    except Exception:
                        pass
                    lines.append(stripped)

            if replaced:
                tmp_path = self.store_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                tmp_path.replace(self.store_path)
                return record["id"]

        with open(self.store_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return rec_id

    def recall(
        self,
        bank_id: str,
        query: str,
        tags: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[RecalledMemory]:
        """
        Retrieve matching records using deterministic tag filtering and keyword overlap.
        Explicitly sets is_offline_fallback=True on returned RecalledMemory items.
        """
        if not self.store_path.exists():
            return []

        candidates: List[Dict[str, Any]] = []
        with open(self.store_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    candidates.append(json.loads(line))
                except Exception:
                    pass

        # Filter by bank_id
        candidates = [c for c in candidates if c.get("bank_id") == bank_id]

        # Tag-based filtering
        tag_set = {t.lower() for t in tags} if tags else set()
        vendor_tags = {t for t in tag_set if t.startswith("vendor:")}

        if tags:
            filtered_candidates = []
            for c in candidates:
                c_tags = {ct.lower() for ct in c.get("tags", [])}
                # If vendor tag is specified, candidate MUST match the vendor tag
                if vendor_tags and not any(vt in c_tags for vt in vendor_tags):
                    continue
                # Must match at least one query tag
                if any(t in c_tags for t in tag_set):
                    filtered_candidates.append(c)
            candidates = filtered_candidates

        # Keyword relevance scoring (Jaccard token overlap + tag bonus)
        q_tokens = set(query.lower().split())
        scored: List[tuple[float, Dict[str, Any]]] = []

        for c in candidates:
            c_tags = {ct.lower() for ct in c.get("tags", [])}
            c_text = (c.get("content", "") + " " + " ".join(c.get("tags", []))).lower()
            c_tokens = set(c_text.split())
            overlap = len(q_tokens.intersection(c_tokens))
            tag_overlap = len(tag_set.intersection(c_tags)) if tags else 0
            base_score = round(overlap / max(len(q_tokens), 1), 3)
            # Give scoring boost to documents matching multiple tags (e.g. vendor + exception)
            score = round(base_score + (tag_overlap * 0.1), 3)
            scored.append((score, c))

        # Sort descending by score, take top limit
        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[RecalledMemory] = []

        for score, c in scored[:limit]:
            results.append(
                RecalledMemory(
                    id=c.get("id", ""),
                    text=c.get("content", ""),
                    type="offline_observation",
                    document_id=c.get("document_id"),
                    tags=c.get("tags", []),
                    metadata=c.get("metadata", {}),
                    score=score,
                    semantic_score=None,
                    keyword_score=score,
                    is_offline_fallback=True,
                    bank_id=c.get("bank_id", bank_id),
                )
            )

        return results

    def get_all(self, bank_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all raw records optionally filtered by bank_id."""
        if not self.store_path.exists():
            return []
        items = []
        with open(self.store_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if bank_id is None or data.get("bank_id") == bank_id:
                        items.append(data)
                except Exception:
                    pass
        return items

