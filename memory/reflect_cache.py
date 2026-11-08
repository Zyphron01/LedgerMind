"""
memory/reflect_cache.py
────────────────────────────────────────────────────────────────────────────────
Disk-Persisted Vendor Profile Cache for Hindsight reflect().

Guarantees:
  1. Vendor-level reflect results are cached to disk (reflect_cache.json).
  2. Never invoked per-invoice; only called when cache misses or during explicit refresh.
  3. Provides invalidation per vendor or across all vendors.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional

from memory.schema import ReflectSummary

ROOT_DIR = Path(__file__).resolve().parent.parent
REFLECT_CACHE_FILE = ROOT_DIR / "reflect_cache.json"


class ReflectCache:
    """Manages persistent cache of synthesized vendor profiles."""

    def __init__(self, cache_path: Path = REFLECT_CACHE_FILE) -> None:
        self.cache_path = Path(cache_path)
        self.data: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️  Warning: Failed to load reflect cache ({e}); starting empty.")
        return {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, default=str)

    def get(self, vendor_slug: str) -> Optional[ReflectSummary]:
        """Retrieve cached reflect summary for vendor if present."""
        slug = vendor_slug.strip().lower()
        item = self.data.get(slug)
        if not item:
            return None
        try:
            gen_at = datetime.fromisoformat(item["generated_at"])
        except Exception:
            gen_at = datetime.now(timezone.utc)

        return ReflectSummary(
            vendor_slug=slug,
            summary=item["summary"],
            generated_at=gen_at,
            cached=True,
        )

    def set(self, vendor_slug: str, summary: str) -> ReflectSummary:
        """Store synthesized reflect summary in disk cache."""
        slug = vendor_slug.strip().lower()
        now = datetime.now(timezone.utc)
        self.data[slug] = {
            "vendor_slug": slug,
            "summary": summary,
            "generated_at": now.isoformat(),
        }
        self._save()
        return ReflectSummary(
            vendor_slug=slug,
            summary=summary,
            generated_at=now,
            cached=False,
        )

    def invalidate(self, vendor_slug: Optional[str] = None) -> int:
        """
        Invalidate cache entry for one vendor or all vendors.
        Returns count of removed entries.
        """
        if vendor_slug is not None:
            slug = vendor_slug.strip().lower()
            if slug in self.data:
                del self.data[slug]
                self._save()
                return 1
            return 0
        else:
            count = len(self.data)
            self.data = {}
            self._save()
            return count

    def is_fresh(self, vendor_slug: str, max_age_hours: int = 24) -> bool:
        """Check if cached profile is within freshness threshold."""
        item = self.get(vendor_slug)
        if not item:
            return False
        age_seconds = (datetime.now(timezone.utc) - item.generated_at).total_seconds()
        return age_seconds <= (max_age_hours * 3600)

