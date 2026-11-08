"""
data/seed.py
────────────────────────────────────────────────────────────────────────────────
Idempotent Seeding Utility for LedgerMind Persistent Memory (Hindsight).

Loads historical Accounts-Payable exception decisions and retains them into
the configured Hindsight bank with backdated timestamps, structured tags,
Pydantic metadata, and factual narratives.

Guarantees:
  1. Strict Idempotency: Local ledger keyed on sha256(bank_id | invoice_number).
  2. Safety Guard: Held-out evaluation invoices are strictly excluded and blocked.
  3. Rate-Limit Pacing: Paces retain calls (default 10s) to adhere to Groq TPM limits.
  4. Non-Automatic Execution: Never runs on startup; manual CLI tool only.

Usage:
  python -m data.seed --sample 3
  python -m data.seed --dry-run
  python -m data.seed --bank-id ledgermind-ap-exceptions --pace-seconds 10
  python -m data.seed --reset-ledger --sample 5
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set

# Ensure site-packages and project root are accessible
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ROOT_DIR / ".env")
except Exception:
    pass

from hindsight_client import Hindsight
from data.models import HistoricalDecision
from data.synthetic import HISTORICAL_FILE, HELD_OUT_FILE, load_historical_decisions

LEDGER_FILE = ROOT_DIR / "data" / "seed_ledger.json"


def compute_idempotency_key(bank_id: str, invoice_number: str) -> str:
    """
    Compute deterministic SHA-256 idempotency key for bank + invoice pair.
    Guarantees cross-bank isolation (sha256(bank1|inv) != sha256(bank2|inv)).
    """
    payload = f"{bank_id.strip()}|{invoice_number.strip()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SeedLedger:
    """Manages persistent JSON ledger of seeded records per bank."""

    def __init__(self, ledger_path: Path = LEDGER_FILE) -> None:
        self.ledger_path = Path(ledger_path)
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.ledger_path.exists():
            try:
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️  Warning: Failed to read ledger file ({e}); initializing fresh.")
        return {"banks": {}}

    def save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, default=str)

    def is_seeded(self, bank_id: str, invoice_number: str) -> bool:
        key = compute_idempotency_key(bank_id, invoice_number)
        bank_ledger = self.data.get("banks", {}).get(bank_id, {})
        return key in bank_ledger

    def record_seeded(
        self,
        bank_id: str,
        invoice_number: str,
        document_id: str,
        vendor_name: str,
        exception_type: str,
        decision: str,
    ) -> None:
        key = compute_idempotency_key(bank_id, invoice_number)
        if "banks" not in self.data:
            self.data["banks"] = {}
        if bank_id not in self.data["banks"]:
            self.data["banks"][bank_id] = {}

        self.data["banks"][bank_id][key] = {
            "invoice_number": invoice_number,
            "document_id": document_id,
            "vendor_name": vendor_name,
            "exception_type": exception_type,
            "decision": decision,
            "seeded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def reset_bank(self, bank_id: str) -> int:
        bank_ledger = self.data.get("banks", {}).get(bank_id, {})
        count = len(bank_ledger)
        if bank_id in self.data.get("banks", {}):
            del self.data["banks"][bank_id]
            self.save()
        return count


def load_held_out_invoice_numbers(held_out_path: str = HELD_OUT_FILE) -> Set[str]:
    """Load invoice numbers from held-out set to enforce safety isolation."""
    p = Path(held_out_path)
    if not p.exists():
        return set()
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["invoice"]["invoice_number"] for item in data}


def seed_historical_records(
    bank_id: str,
    historical_path: str = HISTORICAL_FILE,
    sample_limit: Optional[int] = None,
    pace_seconds: float = 10.0,
    dry_run: bool = False,
    force: bool = False,
    reset_ledger: bool = False,
    client: Optional[Hindsight] = None,
) -> Dict[str, Any]:
    """
    Core seeding function with idempotency verification and safety guards.

    Args:
        bank_id: Target Hindsight bank identifier.
        historical_path: Path to historical_decisions.json.
        sample_limit: Maximum records to seed (None for all).
        pace_seconds: Delay between retain API calls.
        dry_run: If True, simulate operations without calling Hindsight API.
        force: If True, ignore existing ledger entries.
        reset_ledger: If True, clear existing ledger for this bank prior to seeding.
        client: Optional pre-configured Hindsight client instance.

    Returns:
        Summary dict containing counts of total, seeded, skipped, and errors.
    """
    ledger = SeedLedger()

    if reset_ledger:
        cleared = ledger.reset_bank(bank_id)
        print(f"🔄 Reset ledger for bank '{bank_id}' ({cleared} records cleared).")

    # 1. Load historical decisions
    history = load_historical_decisions(historical_path)
    if sample_limit is not None and sample_limit > 0:
        history = history[:sample_limit]

    # 2. STRICT SAFETY GUARD: Verify no held-out invoice is in the batch
    held_out_invoices = load_held_out_invoice_numbers()
    for rec in history:
        if rec.invoice.invoice_number in held_out_invoices:
            raise ValueError(
                f"FATAL SAFETY VIOLATION: Invoice {rec.invoice.invoice_number} is in the held-out "
                f"evaluation set and MUST NOT be seeded into Hindsight memory!"
            )

    print(f"\n{'═' * 70}")
    print(f"  LedgerMind Memory Seeding Engine")
    print(f"  Target Bank:    {bank_id}")
    print(f"  Records Loaded: {len(history)}")
    print(f"  Dry Run:        {dry_run}")
    print(f"  Pace Delay:     {pace_seconds}s per call")
    print(f"{'═' * 70}\n")

    summary = {
        "bank_id": bank_id,
        "total_records": len(history),
        "seeded_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "records": [],
    }

    # Initialize client if not dry-run and not provided
    own_client = False
    if not dry_run and client is None:
        hindsight_mode = os.getenv("HINDSIGHT_MODE", "local")
        hindsight_url = (
            os.getenv("HINDSIGHT_LOCAL_URL", "http://localhost:8888")
            if hindsight_mode == "local"
            else os.getenv("HINDSIGHT_CLOUD_URL", "https://api.hindsight.vectorize.io")
        )
        api_key = os.getenv("HINDSIGHT_API_KEY", "") or None
        client = Hindsight(base_url=hindsight_url, api_key=api_key)
        own_client = True

    try:
        for idx, rec in enumerate(history, 1):
            inv_no = rec.invoice.invoice_number
            doc_id = rec.document_id
            vendor = rec.invoice.vendor_name
            primary_exc = (
                rec.match_result.primary_discrepancy.exception_type.value
                if rec.match_result.primary_discrepancy
                else "NONE"
            )
            decision = rec.decision.value

            # Check idempotency
            if not force and ledger.is_seeded(bank_id, inv_no):
                print(f"[{idx:02d}/{len(history):02d}] ⏭️  [SKIPPED] {inv_no} ({vendor}) — already seeded in '{bank_id}'", flush=True)
                summary["skipped_count"] += 1
                summary["records"].append({
                    "invoice_number": inv_no,
                    "status": "SKIPPED",
                    "reason": "already_in_ledger",
                })
                continue

            narrative = rec.to_narrative()
            metadata = rec.to_metadata()
            tags = rec.tags

            if dry_run:
                print(f"[{idx:02d}/{len(history):02d}] 🔍 [DRY-RUN] Would seed {inv_no} ({vendor}) | DocID: {doc_id}", flush=True)
                summary["seeded_count"] += 1
                summary["records"].append({
                    "invoice_number": inv_no,
                    "status": "DRY_RUN",
                    "doc_id": doc_id,
                })
                continue

            # Retain into Hindsight with backoff retry
            max_retries = 3
            success = False
            for attempt in range(1, max_retries + 1):
                try:
                    assert client is not None
                    t_start = time.time()
                    resp = client.retain(
                        bank_id=bank_id,
                        content=narrative,
                        timestamp=rec.timestamp.isoformat(),
                        context="accounts-payable exception resolution",
                        document_id=doc_id,
                        tags=tags,
                        metadata=metadata,
                        retain_async=False,
                    )
                    elapsed = time.time() - t_start

                    # Record in ledger
                    ledger.record_seeded(
                        bank_id=bank_id,
                        invoice_number=inv_no,
                        document_id=doc_id,
                        vendor_name=vendor,
                        exception_type=primary_exc,
                        decision=decision,
                    )

                    print(
                        f"[{idx:02d}/{len(history):02d}] ✅ [SEEDED] {inv_no} ({vendor}) "
                        f"— {primary_exc} → {decision} ({elapsed:.1f}s)",
                        flush=True,
                    )
                    summary["seeded_count"] += 1
                    summary["records"].append({
                        "invoice_number": inv_no,
                        "status": "SEEDED",
                        "document_id": doc_id,
                        "elapsed_seconds": round(elapsed, 2),
                    })
                    success = True
                    break

                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg or "rate limit" in err_msg.lower():
                        backoff = 15 * attempt
                        print(f"  ⏳ [429 RATE LIMIT] Backing off {backoff}s (attempt {attempt}/{max_retries})...", flush=True)
                        time.sleep(backoff)
                    else:
                        print(f"  ❌ [ERROR] Failed to seed {inv_no} on attempt {attempt}: {err_msg}", flush=True)
                        if attempt == max_retries:
                            summary["error_count"] += 1
                            summary["records"].append({
                                "invoice_number": inv_no,
                                "status": "ERROR",
                                "error": err_msg,
                            })

            # Pacing delay between retain operations to respect Groq TPM
            if success and idx < len(history) and pace_seconds > 0:
                time.sleep(pace_seconds)

    finally:
        if own_client and client is not None:
            try:
                client.close()
            except Exception:
                pass

    print(f"\n{'═' * 70}")
    print(f"  Seeding Complete Summary")
    print(f"  Total Processed: {len(history)}")
    print(f"  Successfully Seeded: {summary['seeded_count']}")
    print(f"  Skipped (Idempotent): {summary['skipped_count']}")
    print(f"  Errors Encountered:  {summary['error_count']}")
    print(f"{'═' * 70}\n")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="LedgerMind Hindsight Memory Seeding CLI")
    parser.add_argument(
        "--bank-id",
        type=str,
        default=os.getenv("HINDSIGHT_BANK_ID", "ledgermind-ap-exceptions"),
        help="Target Hindsight bank ID",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Seed only the first N historical records",
    )
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=10.0,
        help="Delay in seconds between retain calls (default: 10.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate seeding without sending requests to Hindsight",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-seeding regardless of local ledger status",
    )
    parser.add_argument(
        "--reset-ledger",
        action="store_true",
        help="Clear existing ledger records for target bank before seeding",
    )
    args = parser.parse_args()

    seed_historical_records(
        bank_id=args.bank_id,
        sample_limit=args.sample,
        pace_seconds=args.pace_seconds,
        dry_run=args.dry_run,
        force=args.force,
        reset_ledger=args.reset_ledger,
    )


if __name__ == "__main__":
    main()

