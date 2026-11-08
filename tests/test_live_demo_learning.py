"""
tests/test_live_demo_learning.py
────────────────────────────────────────────────────────────────────────────────
Tests for Milestone 4 Learning Demo Bank Workflow:
  1. Preserves baseline evaluation bank without contamination.
  2. Reads authorized baseline context alongside live demo feedback.
  3. Retains new human outcomes exclusively into LIVE_DEMO_BANK_ID.
  4. Makes new feedback immediately available to subsequent demo recommendations.
  5. Clearly identifies which bank each recalled result came from.
"""

from decimal import Decimal
import pytest

from agent.feedback import FeedbackSubmission, process_human_feedback
from agent.resolver import ResolutionAgent
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, ApproverRole, ExceptionType
from data.synthetic import load_held_out_invoices
from memory.client import MemoryClient
from memory.schema import MemoryMode


def test_live_demo_bank_learning_and_isolation():
    """Verify live demo learning loop and frozen baseline non-contamination."""
    # Use offline mode for fast, deterministic unit test execution
    mem_client = MemoryClient(mode=MemoryMode.OFFLINE)
    held_out = load_held_out_invoices()
    target = held_out[0]  # INV-PI-2025-101 (Prabhav Infosystems)

    # 1. Baseline bank starts with some offline historical records
    mem_client.retain(
        bank_id=BASELINE_EVAL_BANK_ID,
        content="Invoice INV-PI-2024-001 from Prabhav Infosystems. Decision: EDITED.",
        document_id="decision-INV-PI-2024-001",
        tags=["vendor:prabhav-infosystems", "exception:price_mismatch", "decision:edited"],
        metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "price_mismatch"},
    )

    # 2. Submit new human review into LIVE_DEMO_BANK_ID
    feedback = FeedbackSubmission(
        invoice_number=target.invoice.invoice_number,
        vendor_name=target.invoice.vendor_name,
        exception_type=target.match_result.exception_type.value,
        agent_proposal="EDITED unit rate to contracted PO rate",
        human_decision=ApproverDecision.EDITED,
        approver_role=ApproverRole.AP_MANAGER,
        human_explanation="Confirmed unit rate markup exceeds contract ceiling. Adjusted to PO rate.",
        final_amount_inr=Decimal("212400.00"),
        cited_memory_ids=["decision-INV-PI-2024-001"],
    )

    result = process_human_feedback(
        submission=feedback,
        memory_client=mem_client,
        bank_id=LIVE_DEMO_BANK_ID,
    )

    assert result.document_id == f"feedback-{target.invoice.invoice_number}"
    assert result.status == "RETAINED"

    # 3. Verify that BASELINE_EVAL_BANK_ID was NOT modified with feedback
    baseline_records = mem_client.offline_store.get_all(bank_id=BASELINE_EVAL_BANK_ID)
    baseline_feedback_records = [r for r in baseline_records if "feedback" in str(r.get("document_id", ""))]
    assert len(baseline_feedback_records) == 0, "Baseline evaluation bank was contaminated!"

    # 4. Resolve using LIVE_DEMO_BANK_ID - should recall BOTH live feedback AND baseline precedent
    mock_llm = type("MockLLMClient", (), {
        "call_json": lambda *a, **k: ({
            "proposed_action": "EDITED",
            "proposed_amount_inr": "212400.00",
            "reasoning": "Edited unit rate to contracted PO rate per prior feedback and baseline precedent.",
            "cited_memory_ids": [f"feedback-{target.invoice.invoice_number}", "decision-INV-PI-2024-001"],
        }, {"total_tokens": 150}),
    })()

    agent = ResolutionAgent(
        memory_client=mem_client,
        llm_client=mock_llm,
        default_bank_id=LIVE_DEMO_BANK_ID,
    )
    proposal = agent.resolve(
        invoice=target.invoice,
        po=target.po,
        grn=target.grn,
        match_result=target.match_result,
        memory_enabled=True,
        bank_id=LIVE_DEMO_BANK_ID,
    )

    # Verify both banks are represented
    recalled_bank_ids = {m.bank_id for m in proposal.recalled_memories}
    assert LIVE_DEMO_BANK_ID in recalled_bank_ids, f"Expected {LIVE_DEMO_BANK_ID} in recalled bank IDs"
    assert BASELINE_EVAL_BANK_ID in recalled_bank_ids, f"Expected {BASELINE_EVAL_BANK_ID} in recalled bank IDs"

    # Verify the feedback document is in supporting documents or recalled memories
    recalled_docs = [m.document_id for m in proposal.recalled_memories]
    assert f"feedback-{target.invoice.invoice_number}" in recalled_docs
    assert any(doc.startswith("decision-INV-PI-") for doc in recalled_docs)

    # Verify high confidence with combined evidence
    assert proposal.confidence.sample_size_n >= 2
    assert proposal.confidence.score > 0.0
