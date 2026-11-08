"""
agent/confidence.py
────────────────────────────────────────────────────────────────────────────────
Deterministic Evidence-Grounded Confidence Scoring Engine for LedgerMind.

Guarantees (Milestone 3.1):
  1. Groups retrieved memory facts by source document_id.
  2. Deduplicates before scoring: counts each unique historical decision AT MOST ONCE.
  3. Verifies decision outcomes and excludes memories without verified source identity.
  4. Strictly excludes out-of-scope decisions (unrelated vendors or exception categories).
  5. Resolves conflicting facts from the same document (excludes unresolvable conflicts).
  6. Discloses exact supporting document IDs and decision breakdown.
  7. Computes confidence via approved formula:
       base = min(n / 8, 1.0)
       consistency = agreement_count / n
       confidence = 0.4 * base + 0.6 * consistency
"""

from collections import Counter, defaultdict
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from data.models import ApproverDecision, ExceptionType
from memory.schema import RecalledMemory


class ConfidenceBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ConfidenceScore(BaseModel):
    """Structured confidence evaluation derived strictly from unique, verified historical decisions as an evidence-consistency heuristic."""
    score: float = Field(description="Numerical evidence-consistency heuristic score between 0.0 and 1.0 (not a statistical probability of correctness)")
    band: ConfidenceBand = Field(description="Categorical confidence band: HIGH (>=0.75), MEDIUM (>=0.45), LOW (<0.45)")
    sample_size_n: int = Field(description="Number of unique, verified historical decisions analyzed")
    agreement_count: int = Field(description="Number of unique historical decisions agreeing with proposal")
    consistency: float = Field(description="Fraction of unique historical decisions in agreement")
    dominant_decision: Optional[ApproverDecision] = Field(default=None, description="Most frequent past human decision")
    supporting_document_ids: List[str] = Field(default_factory=list, description="Unique source document IDs contributing to score")
    decision_breakdown: Dict[str, int] = Field(default_factory=dict, description="Count of decisions by action type across unique documents")
    excluded_memories_count: int = Field(default=0, description="Count of memory items excluded (duplicates, out-of-scope, unverified)")
    explanation: str = Field(description="Human-readable justification of confidence calculation")


def extract_decision_from_memory(mem: RecalledMemory) -> Optional[ApproverDecision]:
    """Extract verified human decision from memory metadata, tags, or narrative text."""
    # 1. Authoritative structured metadata
    meta_dec = mem.metadata.get("decision")
    if meta_dec:
        try:
            return ApproverDecision(str(meta_dec).strip().upper())
        except Exception:
            pass

    # 2. Authoritative structured tags
    for tag in mem.tags:
        if tag.startswith("decision:"):
            val = tag.split(":", 1)[1].strip().upper()
            try:
                return ApproverDecision(val)
            except Exception:
                pass

    # 3. Strict narrative pattern matching (e.g. "DECISION BY <ROLE>: <DECISION>")
    text_upper = mem.text.upper()
    for decision in ApproverDecision:
        if f"DECISION BY" in text_upper and decision.value in text_upper:
            return decision

    return None


def is_memory_in_scope(
    mem: RecalledMemory,
    expected_vendor_slug: Optional[str] = None,
    expected_exception_type: Optional[ExceptionType] = None,
) -> bool:
    """Verify that a recalled memory belongs strictly to the requested vendor and exception scope."""
    # Check vendor scope if specified
    if expected_vendor_slug:
        slug = expected_vendor_slug.strip().lower()
        has_vendor_tag = any(t.lower() == f"vendor:{slug}" for t in mem.tags)
        meta_vendor_slug = mem.metadata.get("vendor_name", "").lower().replace(" ", "-").replace(".", "")
        if not has_vendor_tag and slug not in meta_vendor_slug:
            return False

    # Check exception category scope if specified
    if expected_exception_type:
        exc_str = expected_exception_type.value.lower()
        has_exc_tag = any(t.lower() == f"exception:{exc_str}" for t in mem.tags)
        meta_exc = str(mem.metadata.get("exception_type", "")).lower()
        if not has_exc_tag and meta_exc != exc_str:
            return False

    return True


def deduplicate_historical_decisions(
    historical_memories: List[RecalledMemory],
    expected_vendor_slug: Optional[str] = None,
    expected_exception_type: Optional[ExceptionType] = None,
) -> Tuple[Dict[str, ApproverDecision], int]:
    """
    Groups memory facts by source document_id and enforces decision integrity:
      - Ignores facts without a verified document_id.
      - Discards out-of-scope facts (unrelated vendor or exception).
      - Collects decisions per document.
      - If facts from one document yield conflicting decisions, rejects the document.
      - Deduplicates multiple facts from one document into exactly one decision.

    Returns:
        (verified_decisions_by_doc_id, total_excluded_memories_count)
    """
    doc_decisions: Dict[str, Set[ApproverDecision]] = defaultdict(set)
    total_excluded = 0

    for mem in historical_memories:
        # Require verifiable source document identity
        doc_id = mem.document_id
        if not doc_id:
            total_excluded += 1
            continue

        # Filter out unrelated vendors or exception categories
        if not is_memory_in_scope(mem, expected_vendor_slug, expected_exception_type):
            total_excluded += 1
            continue

        # Extract verified decision
        decision = extract_decision_from_memory(mem)
        if decision is None:
            total_excluded += 1
            continue

        doc_decisions[doc_id].add(decision)

    verified: Dict[str, ApproverDecision] = {}
    for doc_id, dec_set in doc_decisions.items():
        if len(dec_set) == 1:
            verified[doc_id] = next(iter(dec_set))
        else:
            # Conflicting decisions from same document -> exclude for integrity
            total_excluded += len(dec_set)

    return verified, total_excluded


def calculate_confidence(
    proposed_decision: ApproverDecision,
    historical_memories: List[RecalledMemory],
    expected_vendor_slug: Optional[str] = None,
    expected_exception_type: Optional[ExceptionType] = None,
) -> ConfidenceScore:
    """
    Compute deterministic confidence from unique, deduplicated, and verified historical decisions.

    Formula:
      n = number of unique relevant historical decisions (source documents)
      base = min(n / 8, 1.0)
      consistency = agreement_count / n
      confidence = 0.4 * base + 0.6 * consistency
    """
    verified_decisions, excluded_count = deduplicate_historical_decisions(
        historical_memories=historical_memories,
        expected_vendor_slug=expected_vendor_slug,
        expected_exception_type=expected_exception_type,
    )

    n = len(verified_decisions)
    supporting_docs = sorted(list(verified_decisions.keys()))

    # Handle n = 0 safely
    if n == 0:
        return ConfidenceScore(
            score=0.0,
            band=ConfidenceBand.LOW,
            sample_size_n=0,
            agreement_count=0,
            consistency=0.0,
            dominant_decision=None,
            supporting_document_ids=[],
            decision_breakdown={},
            excluded_memories_count=excluded_count,
            explanation=(
                f"No verified historical decisions found matching vendor '{expected_vendor_slug or 'all'}' "
                f"and exception '{expected_exception_type.value if expected_exception_type else 'all'}'; "
                f"confidence set to 0.0 (LOW)."
            ),
        )

    # Count agreements across unique documents
    counts = Counter(verified_decisions.values())
    agreement_count = counts.get(proposed_decision, 0)
    dominant_decision, _ = counts.most_common(1)[0]
    breakdown = {d.value: count for d, count in counts.items()}

    # Calculate metrics
    base = min(n / 8.0, 1.0)
    consistency = agreement_count / n
    score = round(0.4 * base + 0.6 * consistency, 3)

    if score >= 0.75:
        band = ConfidenceBand.HIGH
    elif score >= 0.45:
        band = ConfidenceBand.MEDIUM
    else:
        band = ConfidenceBand.LOW

    explanation = (
        f"Confidence {score:.2f} ({band.value}) derived from {n} unique historical decisions "
        f"({agreement_count}/{n} agree with {proposed_decision.value}, {consistency * 100:.1f}% consistency; "
        f"base volume score: {base:.2f}; {excluded_count} memory items deduplicated/excluded)."
    )

    return ConfidenceScore(
        score=score,
        band=band,
        sample_size_n=n,
        agreement_count=agreement_count,
        consistency=round(consistency, 3),
        dominant_decision=dominant_decision,
        supporting_document_ids=supporting_docs,
        decision_breakdown=breakdown,
        excluded_memories_count=excluded_count,
        explanation=explanation,
    )
