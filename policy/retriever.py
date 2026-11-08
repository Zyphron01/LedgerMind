"""
policy/retriever.py
────────────────────────────────────────────────────────────────────────────────
Deterministic Policy Retrieval Engine for LedgerMind.
Retrieves applicable internal corporate policies based on exception type,
effective date ranges, and versioning.
"""

from datetime import date
from typing import List, Optional

from data.models import ExceptionType
from policy.corpus import POLICIES
from policy.models import CompanyPolicy


class PolicyRetriever:
    """Thread-safe deterministic policy retriever with temporal version scoping."""

    def __init__(self, corpus: Optional[List[CompanyPolicy]] = None) -> None:
        self.corpus: List[CompanyPolicy] = corpus if corpus is not None else POLICIES

    def get_applicable_policy(
        self,
        exception_type: ExceptionType,
        as_of_date: Optional[date] = None,
        policy_id: Optional[str] = None,
    ) -> Optional[CompanyPolicy]:
        """
        Retrieve the authoritative governing policy for a specific exception type and date.

        Args:
            exception_type: Primary 3-way match exception category.
            as_of_date: Date of the transaction (defaults to current date). Used to select correct version.
            policy_id: Optional specific policy ID filter.

        Returns:
            The governing CompanyPolicy instance, or None if unknown.
        """
        target_date = as_of_date or date.today()

        candidates: List[CompanyPolicy] = []
        for pol in self.corpus:
            # Check policy_id if specified
            if policy_id and pol.policy_id != policy_id:
                continue

            # Check exception type
            if exception_type not in pol.applicable_exception_types:
                continue

            # Check temporal validity
            if pol.effective_from <= target_date:
                if pol.effective_to is None or target_date <= pol.effective_to:
                    candidates.append(pol)

        if not candidates:
            return None

        # Prefer most specific version (sort by version descending)
        candidates.sort(key=lambda p: [int(x) for x in p.version.split(".")], reverse=True)
        return candidates[0]

    def get_policy_by_id_and_version(self, policy_id: str, version: str) -> Optional[CompanyPolicy]:
        """Lookup exact historical policy by ID and version string."""
        for pol in self.corpus:
            if pol.policy_id == policy_id and pol.version == version:
                return pol
        return None

    def list_all_policies(self) -> List[CompanyPolicy]:
        """Return full policy corpus."""
        return list(self.corpus)
