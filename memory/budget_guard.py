"""
memory/budget_guard.py
────────────────────────────────────────────────────────────────────────────────
Token and API Call Budget Guard for LedgerMind.

Guarantees:
  1. In CLOUD mode: Enforces configurable caps (500k retain tokens, 100 reflect calls)
     and strictly refuses operations once limits are reached.
  2. In LOCAL mode: Logs and tracks all usage without blocking.
  3. Appends every operation to budget_log.jsonl for complete auditability.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
BUDGET_LOG_FILE = ROOT_DIR / "budget_log.jsonl"


class BudgetExceededError(RuntimeError):
    """Raised when a Hindsight operation would exceed configured cloud budget caps."""
    pass


class BudgetGuard:
    """Tracks token and call budgets for Hindsight retain and reflect calls."""

    def __init__(
        self,
        log_path: Path = BUDGET_LOG_FILE,
        max_retain_tokens: Optional[int] = None,
        max_reflect_calls: Optional[int] = None,
    ) -> None:
        self.log_path = Path(log_path)
        self.max_retain_tokens = (
            max_retain_tokens
            if max_retain_tokens is not None
            else int(os.getenv("HINDSIGHT_MAX_RETAIN_TOKENS", "500000"))
        )
        self.max_reflect_calls = (
            max_reflect_calls
            if max_reflect_calls is not None
            else int(os.getenv("HINDSIGHT_MAX_REFLECT_CALLS", "100"))
        )
        self.cumulative_retain_tokens = 0
        self.cumulative_reflect_calls = 0
        self.cumulative_retain_calls = 0
        self._replay_log()

    def _replay_log(self) -> None:
        """Replay existing budget_log.jsonl to maintain state across process restarts."""
        if not self.log_path.exists():
            return
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("allowed", False):
                            op = record.get("operation")
                            if op == "retain":
                                self.cumulative_retain_calls += 1
                                self.cumulative_retain_tokens += record.get("estimated_tokens", 0)
                            elif op == "reflect":
                                self.cumulative_reflect_calls += 1
                    except Exception:
                        pass
        except Exception:
            pass

    def estimate_tokens(self, text: str) -> int:
        """
        Conservative token estimator.
        Uses character count / 3.8 + 100 overhead tokens for Hindsight embedding/metadata.
        """
        if not text:
            return 100
        return int(len(text) / 3.8) + 100

    def _append_log(self, record: Dict[str, Any]) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as e:
            print(f"⚠️  Warning: Failed to write to budget log: {e}")

    def check_and_record_retain(self, bank_id: str, content: str, mode: str) -> int:
        """
        Check retain budget and record usage.
        Raises BudgetExceededError in cloud mode if limit exceeded.
        """
        est_tokens = self.estimate_tokens(content)
        is_cloud = mode.lower() == "cloud"

        if is_cloud and (self.cumulative_retain_tokens + est_tokens > self.max_retain_tokens):
            self._append_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "operation": "retain",
                "bank_id": bank_id,
                "estimated_tokens": est_tokens,
                "allowed": False,
                "reason": f"Exceeded retain token cap ({self.cumulative_retain_tokens} + {est_tokens} > {self.max_retain_tokens})",
            })
            raise BudgetExceededError(
                f"Cloud budget guard refused retain: limit {self.max_retain_tokens} tokens exceeded "
                f"(current: {self.cumulative_retain_tokens}, requested: +{est_tokens})."
            )

        self.cumulative_retain_calls += 1
        self.cumulative_retain_tokens += est_tokens

        self._append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "operation": "retain",
            "bank_id": bank_id,
            "estimated_tokens": est_tokens,
            "allowed": True,
            "cumulative_tokens": self.cumulative_retain_tokens,
            "cumulative_calls": self.cumulative_retain_calls,
        })
        return est_tokens

    def check_and_record_reflect(self, bank_id: str, query: str, mode: str) -> None:
        """
        Check reflect budget and record usage.
        Raises BudgetExceededError in cloud mode if limit exceeded.
        """
        is_cloud = mode.lower() == "cloud"

        if is_cloud and (self.cumulative_reflect_calls + 1 > self.max_reflect_calls):
            self._append_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "operation": "reflect",
                "bank_id": bank_id,
                "query": query[:100],
                "allowed": False,
                "reason": f"Exceeded reflect calls cap ({self.cumulative_reflect_calls} + 1 > {self.max_reflect_calls})",
            })
            raise BudgetExceededError(
                f"Cloud budget guard refused reflect: limit {self.max_reflect_calls} calls exceeded "
                f"(current: {self.cumulative_reflect_calls})."
            )

        self.cumulative_reflect_calls += 1

        self._append_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "operation": "reflect",
            "bank_id": bank_id,
            "query": query[:100],
            "allowed": True,
            "cumulative_reflect_calls": self.cumulative_reflect_calls,
        })

    def get_usage_summary(self) -> Dict[str, Any]:
        """Return current cumulative usage counters and remaining limits."""
        return {
            "cumulative_retain_tokens": self.cumulative_retain_tokens,
            "cumulative_retain_calls": self.cumulative_retain_calls,
            "cumulative_reflect_calls": self.cumulative_reflect_calls,
            "max_retain_tokens": self.max_retain_tokens,
            "max_reflect_calls": self.max_reflect_calls,
            "remaining_retain_tokens": max(0, self.max_retain_tokens - self.cumulative_retain_tokens),
            "remaining_reflect_calls": max(0, self.max_reflect_calls - self.cumulative_reflect_calls),
        }

