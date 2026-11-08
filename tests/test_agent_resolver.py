"""
tests/test_agent_resolver.py
────────────────────────────────────────────────────────────────────────────────
Unit and integration tests for LedgerMind Resolution Agent:
  - Deterministic confidence scoring
  - Memory citation integrity (no hallucinations)
  - Memory ON vs Memory OFF behavior
  - Structured proposal validation
  - Human feedback processing and duplicate prevention
  - Evaluation label isolation
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
import pytest

from agent.confidence import calculate_confidence, ConfidenceBand, ConfidenceScore
from agent.feedback import FeedbackSubmission, process_human_feedback
from agent.resolver import ResolutionAgent, ResolutionProposal
from agent.llm import GroqClient, LLMError
from data.models import ApproverDecision, ApproverRole, ExceptionType, MatchResult, PurchaseOrder, Invoice
from memory.client import MemoryClient
from memory.schema import MemoryMode, RecalledMemory


def test_confidence_formula_calculation():
    """Verify exact deterministic confidence math across sample sizes and agreement rates."""
    # 1. n = 0 -> score = 0.0, LOW
    score_0 = calculate_confidence(ApproverDecision.APPROVED, [])
    assert score_0.score == 0.0
    assert score_0.band == ConfidenceBand.LOW
    assert score_0.sample_size_n == 0

    # 2. n = 8, 8/8 agree -> base = 1.0, consistency = 1.0 -> 0.4(1.0) + 0.6(1.0) = 1.0 (HIGH)
    mems_8_perfect = [
        RecalledMemory(id=f"m-{i}", document_id=f"doc-{i}", text="Approved", metadata={"decision": "APPROVED"})
        for i in range(8)
    ]
    score_perfect = calculate_confidence(ApproverDecision.APPROVED, mems_8_perfect)
    assert score_perfect.score == 1.0
    assert score_perfect.band == ConfidenceBand.HIGH
    assert score_perfect.agreement_count == 8

    # 3. n = 4, 2/4 agree -> base = 0.5, consistency = 0.5 -> 0.4(0.5) + 0.6(0.5) = 0.50 (MEDIUM)
    mems_4_split = [
        RecalledMemory(id="m-1", document_id="doc-1", text="Approved", metadata={"decision": "APPROVED"}),
        RecalledMemory(id="m-2", document_id="doc-2", text="Approved", metadata={"decision": "APPROVED"}),
        RecalledMemory(id="m-3", document_id="doc-3", text="Edited", metadata={"decision": "EDITED"}),
        RecalledMemory(id="m-4", document_id="doc-4", text="Rejected", metadata={"decision": "REJECTED"}),
    ]
    score_split = calculate_confidence(ApproverDecision.APPROVED, mems_4_split)
    assert score_split.score == 0.50
    assert score_split.band == ConfidenceBand.MEDIUM
    assert score_split.agreement_count == 2

    # 4. n = 2, 0/2 agree -> base = 0.25, consistency = 0.0 -> 0.4(0.25) + 0.0 = 0.10 (LOW)
    mems_2_disagree = [
        RecalledMemory(id="m-1", document_id="doc-1", text="Rejected", metadata={"decision": "REJECTED"}),
        RecalledMemory(id="m-2", document_id="doc-2", text="Rejected", metadata={"decision": "REJECTED"}),
    ]
    score_low = calculate_confidence(ApproverDecision.APPROVED, mems_2_disagree)
    assert score_low.score == 0.10
    assert score_low.band == ConfidenceBand.LOW


def test_citation_hallucination_prevention(sample_po, sample_clean_invoice):
    """
    If the LLM returns cited IDs that were NOT in the recalled memories,
    the resolver MUST strip out the fabricated IDs.
    """
    mock_memory_client = type("MockMemoryClient", (), {
        "mode": MemoryMode.OFFLINE,
        "recall": lambda *a, **k: [
            RecalledMemory(id="mem-valid-01", text="Valid precedent", document_id="doc-valid-01"),
        ],
        "reflect": lambda *a, **k: None,
        "close": lambda: None,
    })()

    # Mock LLM returning valid doc ID + fabricated hallucinated ID
    mock_llm_client = type("MockLLMClient", (), {
        "call_json": lambda *a, **k: ({
            "proposed_action": "EDITED",
            "proposed_amount_inr": "200000.00",
            "reasoning": "Edited per past precedent.",
            "cited_memory_ids": ["doc-valid-01", "doc-HALLUCINATED-99"],
        }, {"total_tokens": 150}),
    })()

    matcher_res = MatchResult(
        is_match=False,
        exception_type=ExceptionType.PRICE_MISMATCH,
        primary_discrepancy=None,
        invoice_number=sample_clean_invoice.invoice_number,
        po_number=sample_po.po_number,
        vendor_name=sample_po.vendor_name,
        invoice_amount_inr=sample_clean_invoice.total_inr,
        expected_amount_inr=sample_po.total_inr,
        explanation="Price mismatch test.",
    )

    agent = ResolutionAgent(
        memory_client=mock_memory_client,
        llm_client=mock_llm_client,
    )

    proposal = agent.resolve(
        invoice=sample_clean_invoice,
        po=sample_po,
        grn=None,
        match_result=matcher_res,
        memory_enabled=True,
    )

    # doc-HALLUCINATED-99 must be stripped out
    assert "doc-valid-01" in proposal.cited_memory_ids
    assert "doc-HALLUCINATED-99" not in proposal.cited_memory_ids


def test_memory_off_behavior(sample_po, sample_clean_invoice):
    """When memory_enabled=False, resolver must not cite memories and should report sample size 0."""
    mock_llm_client = type("MockLLMClient", (), {
        "call_json": lambda *a, **k: ({
            "proposed_action": "REJECTED",
            "proposed_amount_inr": "0.00",
            "reasoning": "Rejected per standard AP match failure policy.",
            "cited_memory_ids": [],
        }, {"total_tokens": 120}),
    })()

    matcher_res = MatchResult(
        is_match=False,
        exception_type=ExceptionType.DUPLICATE_INVOICE,
        primary_discrepancy=None,
        invoice_number=sample_clean_invoice.invoice_number,
        po_number=sample_po.po_number,
        vendor_name=sample_po.vendor_name,
        invoice_amount_inr=sample_clean_invoice.total_inr,
        expected_amount_inr=sample_po.total_inr,
        explanation="Duplicate invoice test.",
    )

    agent = ResolutionAgent(
        memory_client=MemoryClient(mode=MemoryMode.OFFLINE),
        llm_client=mock_llm_client,
    )

    proposal = agent.resolve(
        invoice=sample_clean_invoice,
        po=sample_po,
        grn=None,
        match_result=matcher_res,
        memory_enabled=False,
    )

    assert proposal.memory_enabled is False
    assert len(proposal.cited_memory_ids) == 0
    assert len(proposal.recalled_memories) == 0
    assert proposal.confidence.sample_size_n == 0
    assert proposal.confidence.band == ConfidenceBand.LOW


def test_human_feedback_processing_and_idempotency(tmp_path: Path):
    """Processing human feedback must produce stable document IDs and retain the audit trail."""
    store_file = tmp_path / "feedback_test.jsonl"
    mem_client = MemoryClient(mode=MemoryMode.OFFLINE, offline_store=type("MockStore", (), {
        "retain": lambda *a, **k: "feedback-INV-TEST-001",
        "store_path": store_file,
    })())

    submission = FeedbackSubmission(
        invoice_number="INV-TEST-001",
        vendor_name="Prabhav Infosystems Pvt Ltd",
        exception_type="PRICE_MISMATCH",
        agent_proposal="Proposed EDITED to PO contracted rate ₹200,000",
        human_decision=ApproverDecision.APPROVED,
        approver_role=ApproverRole.FINANCE_CONTROLLER,
        human_explanation="One-time management override approved due to critical quarter-end project delivery.",
        final_amount_inr=Decimal("210000.00"),
        cited_memory_ids=["doc-past-01"],
    )

    res1 = process_human_feedback(submission, mem_client, bank_id="test-feedback-bank")
    assert res1.document_id == "feedback-INV-TEST-001"
    assert res1.status == "RETAINED"
    assert res1.human_decision == ApproverDecision.APPROVED

    # Submitting again for the same invoice must yield the same stable document ID
    res2 = process_human_feedback(submission, mem_client, bank_id="test-feedback-bank")
    assert res2.document_id == res1.document_id


def test_confidence_deduplicates_multiple_facts_same_document():
    """Multiple extracted facts from the same source document must be counted at most ONCE."""
    # 4 distinct memory facts, but 3 belong to doc-01 and 1 belongs to doc-02
    mems = [
        RecalledMemory(
            id="fact-1",
            text="Invoice INV-001 billed rate was 1800",
            document_id="decision-INV-001",
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems", "exception_type": "PRICE_MISMATCH"},
        ),
        RecalledMemory(
            id="fact-2",
            text="AP_MANAGER edited invoice INV-001 to contracted rate",
            document_id="decision-INV-001",
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems", "exception_type": "PRICE_MISMATCH"},
        ),
        RecalledMemory(
            id="fact-3",
            text="Final payout for INV-001 was 178500",
            document_id="decision-INV-001",
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems", "exception_type": "PRICE_MISMATCH"},
        ),
        RecalledMemory(
            id="fact-4",
            text="Invoice INV-002 was also edited to PO ceiling",
            document_id="decision-INV-002",
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems", "exception_type": "PRICE_MISMATCH"},
        ),
    ]

    score = calculate_confidence(
        proposed_decision=ApproverDecision.EDITED,
        historical_memories=mems,
        expected_vendor_slug="prabhav",
        expected_exception_type=ExceptionType.PRICE_MISMATCH,
    )

    # Must count exactly 2 unique documents, NOT 4 facts!
    assert score.sample_size_n == 2
    assert score.agreement_count == 2
    assert score.consistency == 1.0
    assert score.supporting_document_ids == ["decision-INV-001", "decision-INV-002"]


def test_confidence_excludes_conflicting_facts_from_one_document():
    """If facts from the same source document report conflicting decisions, exclude for integrity."""
    mems = [
        RecalledMemory(
            id="fact-1",
            text="Invoice INV-CONFLICT was approved",
            document_id="decision-INV-CONFLICT",
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"decision": "APPROVED", "vendor_name": "Prabhav Infosystems", "exception_type": "PRICE_MISMATCH"},
        ),
        RecalledMemory(
            id="fact-2",
            text="Invoice INV-CONFLICT was rejected",
            document_id="decision-INV-CONFLICT",
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"decision": "REJECTED", "vendor_name": "Prabhav Infosystems", "exception_type": "PRICE_MISMATCH"},
        ),
    ]

    score = calculate_confidence(
        proposed_decision=ApproverDecision.APPROVED,
        historical_memories=mems,
        expected_vendor_slug="prabhav",
        expected_exception_type=ExceptionType.PRICE_MISMATCH,
    )

    # Contradictory document must be excluded
    assert score.sample_size_n == 0
    assert score.score == 0.0
    assert score.band == ConfidenceBand.LOW
    assert len(score.supporting_document_ids) == 0


def test_confidence_excludes_out_of_scope_vendors_and_exceptions():
    """Confidence must strictly exclude unrelated vendors or different exception categories."""
    mems = [
        # In-scope: Prabhav Infosystems + PRICE_MISMATCH
        RecalledMemory(
            id="fact-1",
            text="Prabhav rate overcharge edited",
            document_id="decision-INV-PI-01",
            tags=["vendor:prabhav-infosystems", "exception:price_mismatch"],
            metadata={"decision": "EDITED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "PRICE_MISMATCH"},
        ),
        # Out-of-scope vendor: Kamalnath Supplies
        RecalledMemory(
            id="fact-2",
            text="Kamalnath duplicate rejected",
            document_id="decision-INV-KS-01",
            tags=["vendor:kamalnath-supplies", "exception:duplicate_invoice"],
            metadata={"decision": "REJECTED", "vendor_name": "Kamalnath Supplies Co", "exception_type": "DUPLICATE_INVOICE"},
        ),
        # Out-of-scope exception for same vendor: QUANTITY_SHORTFALL
        RecalledMemory(
            id="fact-3",
            text="Prabhav hardware shortfall approved",
            document_id="decision-INV-PI-SHORT",
            tags=["vendor:prabhav-infosystems", "exception:quantity_shortfall"],
            metadata={"decision": "APPROVED", "vendor_name": "Prabhav Infosystems Pvt Ltd", "exception_type": "QUANTITY_SHORTFALL"},
        ),
    ]

    score = calculate_confidence(
        proposed_decision=ApproverDecision.EDITED,
        historical_memories=mems,
        expected_vendor_slug="prabhav-infosystems",
        expected_exception_type=ExceptionType.PRICE_MISMATCH,
    )

    # Exactly 1 in-scope document
    assert score.sample_size_n == 1
    assert score.agreement_count == 1
    assert score.supporting_document_ids == ["decision-INV-PI-01"]
    assert score.excluded_memories_count == 2


def test_confidence_excludes_unverified_source_identity_or_outcome():
    """Memories without verified document_id or with missing decision must be excluded."""
    mems = [
        # Missing document_id
        RecalledMemory(
            id="fact-no-doc",
            text="Some floating text with no source document",
            document_id=None,
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"decision": "EDITED"},
        ),
        # Missing decision outcome
        RecalledMemory(
            id="fact-no-dec",
            text="Invoice INV-001 was submitted on 2025-01-01",
            document_id="decision-INV-NODEC",
            tags=["vendor:prabhav", "exception:price_mismatch"],
            metadata={"vendor_name": "Prabhav Infosystems", "exception_type": "PRICE_MISMATCH"},
        ),
    ]

    score = calculate_confidence(
        proposed_decision=ApproverDecision.EDITED,
        historical_memories=mems,
        expected_vendor_slug="prabhav",
        expected_exception_type=ExceptionType.PRICE_MISMATCH,
    )

    assert score.sample_size_n == 0
    assert score.excluded_memories_count == 2


def test_benchmark_isolation_guard():
    """Human feedback submissions must be blocked from writing to the frozen baseline benchmark bank."""
    from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID

    mem_client = MemoryClient(mode=MemoryMode.OFFLINE)
    submission = FeedbackSubmission(
        invoice_number="INV-CONTAMINATION-TEST",
        vendor_name="Prabhav Infosystems Pvt Ltd",
        exception_type="PRICE_MISMATCH",
        agent_proposal="EDITED to PO rate",
        human_decision=ApproverDecision.APPROVED,
        human_explanation="Testing benchmark safety guard.",
        final_amount_inr=Decimal("1000.00"),
    )

    # Attempting to write feedback into the frozen baseline evaluation bank MUST raise ValueError
    with pytest.raises(ValueError, match="CONTAMINATION SAFETY VIOLATION"):
        process_human_feedback(
            submission=submission,
            memory_client=mem_client,
            bank_id=BASELINE_EVAL_BANK_ID,
        )

    # Writing to the live demonstration bank must succeed cleanly
    res = process_human_feedback(
        submission=submission,
        memory_client=mem_client,
        bank_id=LIVE_DEMO_BANK_ID,
    )
    assert res.status == "RETAINED"
    assert res.document_id == "feedback-INV-CONTAMINATION-TEST"


