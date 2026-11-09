"""
tests/test_pydantic_regression.py
────────────────────────────────────────────────────────────────────────────────
Regression test verifying that ResolutionProposal correctly accepts and coerces
RecalledMemory objects even when instantiated across different module loads or
simulated stale classes (reproducing the '5 validation errors for ResolutionProposal').
"""

from decimal import Decimal
from typing import Any, List
from pydantic import BaseModel, Field, ValidationError
import pytest

from agent.confidence import ConfidenceBand, ConfidenceScore
from agent.resolver import ResolutionProposal
from data.models import ApproverDecision, ExceptionType
from memory.schema import RecalledMemory
from policy.models import ConflictStatus


# Simulated "stale" or reloaded RecalledMemory class from a different import context
class SimulatedStaleRecalledMemory(BaseModel):
    id: str
    text: str
    type: str = "observation"
    document_id: str
    tags: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    score: float = 0.88
    semantic_score: float = 0.85
    reranker_score: float = 0.88
    keyword_score: float = 0.75
    is_offline_fallback: bool = False
    bank_id: str = "ledgermind-baseline"


def test_resolution_proposal_accepts_five_stale_recalled_memories():
    """
    Reproduces the exact bug where 5 RecalledMemory items from an alternate class
    or reloaded module failed with:
    '5 validation errors for ResolutionProposal: recalled_memories.0 Input should be a valid dictionary or instance of RecalledMemory'
    """
    stale_memories = [
        SimulatedStaleRecalledMemory(
            id=f"mem-{i}",
            document_id=f"DOC-HIST-{i:03d}",
            text=f"Historical resolution rationale for precedent #{i}",
        )
        for i in range(5)
    ]

    conf = ConfidenceScore(
        score=0.85,
        band=ConfidenceBand.HIGH,
        sample_size_n=5,
        agreement_count=4,
        consistency=0.8,
        supporting_document_ids=[f"DOC-HIST-{i:03d}" for i in range(5)],
        decision_breakdown={"APPROVED": 4, "EDITED": 1},
        explanation="0.4*(5/8) + 0.6*(4/5) = 0.85",
    )

    # Must NOT raise ValidationError
    proposal = ResolutionProposal(
        invoice_number="INV-PI-2025-101",
        vendor_name="Prabhav Infosystems",
        exception_type=ExceptionType.PRICE_MISMATCH,
        proposed_action=ApproverDecision.EDITED,
        proposed_amount_inr=Decimal("212400.00"),
        reasoning="Approved at PO rate.",
        confidence=conf,
        memory_enabled=True,
        recalled_memories=stale_memories,
    )

    assert len(proposal.recalled_memories) == 5
    assert all(isinstance(m, RecalledMemory) for m in proposal.recalled_memories)
    assert proposal.recalled_memories[0].document_id == "DOC-HIST-000"
    assert proposal.recalled_memories[4].document_id == "DOC-HIST-004"
