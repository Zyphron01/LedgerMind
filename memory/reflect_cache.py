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
        # Clean any historical corrupted failure strings from cache on initialization
        self.purge_failed_entries()

    @staticmethod
    def is_failed_summary(summary: Any) -> bool:
        """Identify if a summary string or ReflectSummary represents a failure, error message, or test mock placeholder."""
        if summary is None:
            return True
        if hasattr(summary, "is_error") and getattr(summary, "is_error"):
            return True
        if hasattr(summary, "summary"):
            summary_text = getattr(summary, "summary", "")
        else:
            summary_text = str(summary)
        if not summary_text:
            return True
        low = str(summary_text).strip().lower()
        # Reject test placeholders
        if low in ("reflect text", "mock", "placeholder", "test summary", "dummy"):
            return True
        return (
            "reflect generation failed" in low
            or "falling back to direct historical recall" in low
            or "internal server error" in low
            or "provider quota exhausted" in low
            or "rate limit reached" in low
            or "reflect synthesis unavailable" in low
            or "runtimeerror" in low
        )

    def _make_key(self, vendor_slug: str, bank_id: Optional[str] = None) -> str:
        """Construct scoped cache key using bank_id and vendor_slug."""
        slug = vendor_slug.strip().lower()
        if bank_id:
            b = bank_id.strip().lower()
            return f"{b}::{slug}"
        return slug

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

    def purge_failed_entries(self) -> int:
        """Purge any cache entries that contain error messages or failure strings."""
        to_del = [k for k, v in self.data.items() if self.is_failed_summary(v.get("summary", ""))]
        for k in to_del:
            del self.data[k]
        if to_del:
            self._save()
        return len(to_del)

    def get(self, vendor_slug: str, bank_id: Optional[str] = None) -> Optional[ReflectSummary]:
        """Retrieve cached reflect summary for vendor and bank if present and valid."""
        slug = vendor_slug.strip().lower()
        scoped_key = self._make_key(slug, bank_id) if bank_id else None

        # Check bank-scoped key first, then fallback to vendor slug for backward compatibility
        item = None
        matched_key = None
        if scoped_key and scoped_key in self.data:
            item = self.data[scoped_key]
            matched_key = scoped_key
        elif slug in self.data:
            item = self.data[slug]
            matched_key = slug
        elif not bank_id:
            # Fallback for unscoped queries: look for any entry matching this slug
            for k, v in self.data.items():
                if k == slug or k.endswith(f"::{slug}"):
                    item = v
                    matched_key = k
                    break

        if not item:
            return None

        summary_text = item.get("summary", "")
        if self.is_failed_summary(summary_text):
            del self.data[matched_key]
            self._save()
            return None

        try:
            gen_at = datetime.fromisoformat(item["generated_at"])
        except Exception:
            gen_at = datetime.now(timezone.utc)

        return ReflectSummary(
            vendor_slug=slug,
            summary=summary_text,
            generated_at=gen_at,
            cached=True,
            is_error=False,
            bank_id=item.get("bank_id", bank_id),
        )

    def set(self, vendor_slug: str, summary: Any, bank_id: Optional[str] = None) -> ReflectSummary:
        """Store synthesized reflect summary in disk cache (rejects error strings and mock placeholders)."""
        slug = vendor_slug.strip().lower()
        now = datetime.now(timezone.utc)
        summary_text = getattr(summary, "summary", str(summary)) if summary is not None else ""
        if self.is_failed_summary(summary):
            return ReflectSummary(
                vendor_slug=slug,
                summary=summary_text,
                generated_at=now,
                cached=False,
                is_error=True,
                error_message=summary_text,
                bank_id=bank_id,
            )
        cache_key = self._make_key(slug, bank_id) if bank_id else slug
        self.data[cache_key] = {
            "vendor_slug": slug,
            "bank_id": bank_id,
            "summary": summary_text,
            "generated_at": now.isoformat(),
        }
        self._save()
        return ReflectSummary(
            vendor_slug=slug,
            summary=summary_text,
            generated_at=now,
            cached=False,
            is_error=False,
            bank_id=bank_id,
        )

    def invalidate(self, vendor_slug: Optional[str] = None, bank_id: Optional[str] = None) -> int:
        """
        Invalidate cache entry for one vendor or all vendors, with optional bank filter.
        Returns count of removed entries.
        """
        if vendor_slug is not None:
            slug = vendor_slug.strip().lower()
            keys_to_del = []
            if bank_id:
                scoped_key = self._make_key(slug, bank_id)
                if scoped_key in self.data:
                    keys_to_del.append(scoped_key)
            if slug in self.data:
                keys_to_del.append(slug)
            for k in set(keys_to_del):
                del self.data[k]
            if keys_to_del:
                self._save()
            return len(keys_to_del)
        else:
            count = len(self.data)
            self.data = {}
            self._save()
            return count

    def is_fresh(self, vendor_slug: str, bank_id: Optional[str] = None, max_age_hours: int = 24) -> bool:
        """Check if cached profile is within freshness threshold."""
        item = self.get(vendor_slug, bank_id=bank_id)
        if not item:
            return False
        age_seconds = (datetime.now(timezone.utc) - item.generated_at).total_seconds()
        return age_seconds <= (max_age_hours * 3600)
        age_seconds = (datetime.now(timezone.utc) - item.generated_at).total_seconds()
        return age_seconds <= (max_age_hours * 3600)

