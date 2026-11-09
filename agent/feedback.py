"""
agent/feedback.py
────────────────────────────────────────────────────────────────────────────────
Human-in-the-Loop Feedback Engine for LedgerMind.

Captures human approver overrides, edits, rejections, and approvals,
and retains them into persistent Hindsight memory.

Guarantees:
  1. Distinguishes approval of the agent proposal from approval of the underlying payment.
  2. Uses stable document IDs (feedback-{invoice_number}) to prevent duplication.
  3. Preserves audit trail and cited memories.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, ApproverRole
from memory.client import MemoryClient
from memory.operations import retain_human_feedback
from memory.schema import FeedbackRecord


class FeedbackSubmission(BaseModel):
    """Input payload submitted by a human AP reviewer."""
    invoice_number: str
    vendor_name: str
    exception_type: str
    agent_proposal: str
    human_decision: ApproverDecision
    approver_role: ApproverRole = ApproverRole.AP_MANAGER
    human_explanation: str
    final_amount_inr: Decimal
    cited_memory_ids: List[str] = Field(default_factory=list)


class FeedbackResult(BaseModel):
    """Result of human feedback retention into institutional memory."""
    document_id: str
    status: str
    invoice_number: str
    human_decision: ApproverDecision
    retained_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def process_human_feedback(
    submission: FeedbackSubmission,
    memory_client: MemoryClient,
    bank_id: str = LIVE_DEMO_BANK_ID,
) -> FeedbackResult:
    """
    Process human decision and retain outcome into Hindsight memory bank.
    Unconditionally protects the baseline evaluation bank against contamination.

    Args:
        submission: Human reviewer's decision and explanation.
        memory_client: Active MemoryClient instance.
        bank_id: Target Hindsight bank (defaults to live demonstration bank).

    Returns:
        FeedbackResult confirming retention.
    """
    # Strict benchmark isolation safety guard - baseline is permanently read-only for feedback
    if bank_id == BASELINE_EVAL_BANK_ID:
        raise ValueError(
            f"CONTAMINATION SAFETY VIOLATION: Cannot retain human feedback into frozen baseline "
            f"evaluation bank '{bank_id}'! Use the live demonstration bank ('{LIVE_DEMO_BANK_ID}') "
            f"for learning workflows."
        )
    record = FeedbackRecord(
        invoice_number=submission.invoice_number,
        vendor_name=submission.vendor_name,
        exception_type=submission.exception_type,
        agent_proposal=submission.agent_proposal,
        human_decision=submission.human_decision,
        approver_role=submission.approver_role,
        human_reason=submission.human_explanation,
        final_amount_inr=submission.final_amount_inr,
        cited_memory_ids=submission.cited_memory_ids,
        timestamp=datetime.now(timezone.utc),
    )

    doc_id = retain_human_feedback(client=memory_client, bank_id=bank_id, feedback=record)

    return FeedbackResult(
        document_id=doc_id,
        status="RETAINED",
        invoice_number=submission.invoice_number,
        human_decision=submission.human_decision,
    )