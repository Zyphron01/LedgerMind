"""
agent/resolver.py
────────────────────────────────────────────────────────────────────────────────
Deterministic Resolution Agent for LedgerMind.

Orchestrates:
  Invoice Discrepancy → Hindsight Recall → Groq Synthesis → Confidence Scoring
"""

from decimal import Decimal
import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from agent.confidence import calculate_confidence, ConfidenceBand, ConfidenceScore
from agent.llm import GroqClient
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from data.models import ApproverDecision, ExceptionType, GoodsReceiptNote, Invoice, MatchResult, PurchaseOrder
from data.vendors import get_vendor_slug
from memory.client import MemoryClient
from memory.operations import get_vendor_profile, recall_for_confidence, recall_for_exception
from memory.schema import RecalledMemory
from policy.conflict import evaluate_policy_precedent_conflict
from policy.models import ConflictStatus, PolicyConflictEvaluation
from policy.retriever import PolicyRetriever


class ResolutionProposal(BaseModel):
    """Structured resolution recommendation output by the LedgerMind agent."""
    invoice_number: str
    vendor_name: str
    exception_type: ExceptionType
    proposed_action: ApproverDecision
    proposed_amount_inr: Decimal
    reasoning: str
    cited_memory_ids: List[str] = Field(default_factory=list)
    confidence: ConfidenceScore
    memory_enabled: bool = True
    recalled_memories: List[RecalledMemory] = Field(default_factory=list)
    vendor_profile_summary: Optional[str] = None
    token_usage: Dict[str, int] = Field(default_factory=dict)

    # Policy RAG & Conflict Intelligence (Milestone 5)
    policy_id: Optional[str] = None
    policy_version: Optional[str] = None
    policy_title: Optional[str] = None
    quoted_clause: Optional[str] = None
    conflict_status: ConflictStatus = ConflictStatus.POLICY_UNKNOWN
    conflict_explanation: Optional[str] = None
    requires_escalation: bool = False
    escalation_path: Optional[str] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Any) -> Any:
        if hasattr(v, "model_dump"):
            return v.model_dump()
        return v

    @field_validator("recalled_memories", mode="before")
    @classmethod
    def _coerce_recalled_memories(cls, v: Any) -> Any:
        if isinstance(v, list):
            coerced = []
            for item in v:
                if hasattr(item, "model_dump"):
                    coerced.append(item.model_dump())
                elif hasattr(item, "__dict__") and not isinstance(item, dict):
                    coerced.append(dict(item.__dict__))
                else:
                    coerced.append(item)
            return coerced
        return v


def normalize_and_deduplicate_memories(
    memories: List[RecalledMemory],
    max_items: int = 5,
) -> List[RecalledMemory]:
    """
    Groups recalled memory facts by originating source review/document into
    a single logical evidence entry per historical precedent.
    Aggregates extracted sub-facts/observations under the primary entry in supporting_facts,
    preventing any single invoice review from consuming multiple display slots.
    Facts lacking reliable document attribution are labeled as ungrouped facts.
    """
    import re
    from collections import OrderedDict

    verified_groups: Dict[str, List[RecalledMemory]] = OrderedDict()
    unassigned: List[RecalledMemory] = []
    ungrouped_facts: List[RecalledMemory] = []

    # Pass 1: Direct document IDs, metadata invoice numbers, and text citations
    for m in memories:
        doc_id = m.document_id
        if not doc_id and m.metadata.get("invoice_number"):
            inv_num = m.metadata["invoice_number"]
            is_fb = any("feedback" in t.lower() for t in m.tags) or m.metadata.get("source") == "human_feedback"
            doc_id = f"feedback-{inv_num}" if is_fb else f"decision-{inv_num}"
        if not doc_id:
            match = re.search(r"(INV-[A-Za-z0-9-]+)", m.text)
            if match:
                inv_num = match.group(1)
                is_fb = any("feedback" in t.lower() for t in m.tags) or "human" in m.text.lower() or "reviewed" in m.text.lower()
                doc_id = f"feedback-{inv_num}" if is_fb else f"decision-{inv_num}"

        if doc_id:
            m.document_id = doc_id
            m.is_ungrouped = False
            if doc_id not in verified_groups:
                verified_groups[doc_id] = []
            verified_groups[doc_id].append(m)
        else:
            unassigned.append(m)

    # Pass 2: Unambiguous contextual linkage for sub-facts sharing unique vendor + review scope
    for m in unassigned:
        linked_doc_id = None
        v_tag = next((t.split(":", 1)[1] for t in m.tags if t.startswith("vendor:")), None)
        is_fb = any("feedback" in t.lower() for t in m.tags) or m.metadata.get("source") == "human_feedback"

        if v_tag:
            matching_verified = [
                d_id for d_id, grp in verified_groups.items()
                if (d_id.startswith("feedback-") if is_fb else True)
                and any(v_tag in [t.split(":", 1)[1] for t in g.tags if t.startswith("vendor:")] for g in grp)
            ]
            if len(matching_verified) == 1:
                linked_doc_id = matching_verified[0]

        if linked_doc_id:
            m.document_id = linked_doc_id
            m.is_ungrouped = False
            verified_groups[linked_doc_id].append(m)
        else:
            # Cannot be reliably attributed to a parent document -> label as ungrouped fact
            m.is_ungrouped = True
            m.document_id = f"fact-{m.id[:8]}" if m.id else "fact-unattributed"
            ungrouped_facts.append(m)

    logical_entries: List[RecalledMemory] = []

    # 1. First add distinct verified document groups (each historical review occupies exactly 1 entry)
    for doc_id, group in verified_groups.items():
        # Select the most informative primary memory: prefers metadata, longest narrative, then score
        primary = max(group, key=lambda x: (bool(x.metadata), len(x.text), x.score or 0.0))
        # Collect distinct supporting sub-facts
        supporting: List[str] = []
        for fact in group:
            fact_str = fact.text.strip()
            if fact.id != primary.id and fact_str != primary.text.strip():
                if fact_str not in supporting and fact_str not in primary.text:
                    supporting.append(fact_str)
        primary.supporting_facts = supporting
        logical_entries.append(primary)

    # 2. Append ungrouped facts only if remaining display slots exist
    for u in ungrouped_facts:
        if len(logical_entries) >= max_items:
            break
        u.supporting_facts = []
        logical_entries.append(u)

    return logical_entries[:max_items]


class ResolutionAgent:
    """Core autonomous AP resolution agent using Hindsight memory and Groq LLM."""

    def __init__(
        self,
        memory_client: Optional[MemoryClient] = None,
        llm_client: Optional[GroqClient] = None,
        default_bank_id: Optional[str] = None,
        policy_retriever: Optional[PolicyRetriever] = None,
    ) -> None:
        self.memory = memory_client or MemoryClient()
        self.llm = llm_client or GroqClient()
        self.bank_id = default_bank_id or os.getenv("HINDSIGHT_BANK_ID", "ledgermind-ap-exceptions")
        self.policy_retriever = policy_retriever or PolicyRetriever()

    def resolve(
        self,
        invoice: Invoice,
        po: PurchaseOrder,
        grn: Optional[GoodsReceiptNote],
        match_result: MatchResult,
        memory_enabled: bool = True,
        bank_id: Optional[str] = None,
        force_profile_refresh: bool = False,
        enforce_policy_supremacy: bool = True,
    ) -> ResolutionProposal:
        """
        Produce structured resolution proposal for an AP match discrepancy.

        Args:
            invoice: Supplier invoice.
            po: Purchase order.
            grn: Goods receipt note (optional).
            match_result: Deterministic 3-way match result.
            memory_enabled: If False, disables memory recall and runs in zero-context mode.
            bank_id: Target Hindsight bank (overrides default).
            force_profile_refresh: If True, bypasses reflect cache for vendor.

        Returns:
            Validated ResolutionProposal with action, amount, explanation, citations, and confidence.
        """
        target_bank = bank_id or self.bank_id
        vendor_slug = get_vendor_slug(invoice.vendor_name)
        recalled_mems: List[RecalledMemory] = []
        confidence_sample: List[RecalledMemory] = []
        profile_summary: Optional[str] = None

        # Clean 3-way match: immediate deterministic approval
        if match_result.is_match:
            return ResolutionProposal(
                invoice_number=invoice.invoice_number,
                vendor_name=invoice.vendor_name,
                exception_type=match_result.exception_type,
                proposed_action=ApproverDecision.APPROVED,
                proposed_amount_inr=invoice.total_inr,
                reasoning="Clean three-way match: All billed line items, unit prices, quantities, and GST rates fully reconcile with purchase order and warehouse receipt.",
                cited_memory_ids=[],
                confidence=ConfidenceScore(
                    score=1.0,
                    band=ConfidenceBand.HIGH,
                    sample_size_n=0,
                    agreement_count=0,
                    consistency=1.0,
                    explanation="Clean 3-way match: Zero variances detected between invoice, PO, and GRN.",
                ),
                memory_enabled=memory_enabled,
                recalled_memories=[],
                conflict_status=ConflictStatus.COMPLIANT_PRECEDENT,
                conflict_explanation="Clean match conforms with standard procurement controls.",
                requires_escalation=False,
                policy_id="POL-AP-001",
                policy_version="1.0",
                policy_title="Standard Accounts Payable Three-Way Matching Protocol",
                quoted_clause="Invoices matching purchase orders and receiving logs within zero variance shall be approved for payment disbursement.",
            )

        # 0. RETRIEVE GOVERNING CORPORATE POLICY (POLICY RAG)
        governing_policy = self.policy_retriever.get_applicable_policy(
            exception_type=match_result.exception_type,
            as_of_date=invoice.invoice_date,
        )

        # 1. RETRIEVE INSTITUTIONAL MEMORY (if enabled)
        if memory_enabled:
            if target_bank == LIVE_DEMO_BANK_ID:
                # 1a. In Live Demo mode: read from LIVE_DEMO_BANK_ID (recent learning) AND BASELINE_EVAL_BANK_ID (read-only baseline)
                demo_mems = recall_for_exception(
                    client=self.memory,
                    bank_id=LIVE_DEMO_BANK_ID,
                    invoice=invoice,
                    match_result=match_result,
                    limit=5,
                )
                baseline_mems = recall_for_exception(
                    client=self.memory,
                    bank_id=BASELINE_EVAL_BANK_ID,
                    invoice=invoice,
                    match_result=match_result,
                    limit=5,
                )
                # Combine with newly retained live feedback prioritized first
                recalled_mems = normalize_and_deduplicate_memories(demo_mems + baseline_mems, max_items=5)

                # Confidence sample combining both live demo feedback and baseline precedents
                demo_conf = recall_for_confidence(
                    client=self.memory,
                    bank_id=LIVE_DEMO_BANK_ID,
                    vendor_slug=vendor_slug,
                    exception_type=match_result.exception_type,
                    limit=15,
                )
                baseline_conf = recall_for_confidence(
                    client=self.memory,
                    bank_id=BASELINE_EVAL_BANK_ID,
                    vendor_slug=vendor_slug,
                    exception_type=match_result.exception_type,
                    limit=15,
                )
                confidence_sample = normalize_and_deduplicate_memories(demo_conf + baseline_conf, max_items=15)

                # Reflect profile from live demo bank with fallback to baseline
                try:
                    prof = get_vendor_profile(
                        client=self.memory,
                        bank_id=LIVE_DEMO_BANK_ID,
                        vendor_slug=vendor_slug,
                        force_refresh=force_profile_refresh,
                    )
                    if prof and prof.summary:
                        profile_summary = prof.summary
                    else:
                        prof_base = get_vendor_profile(
                            client=self.memory,
                            bank_id=BASELINE_EVAL_BANK_ID,
                            vendor_slug=vendor_slug,
                            force_refresh=force_profile_refresh,
                        )
                        if prof_base and prof_base.summary:
                            profile_summary = prof_base.summary
                except Exception:
                    profile_summary = None

            else:
                # Query specific precedents for this discrepancy
                raw_recalled = recall_for_exception(
                    client=self.memory,
                    bank_id=target_bank,
                    invoice=invoice,
                    match_result=match_result,
                    limit=10,
                )
                recalled_mems = normalize_and_deduplicate_memories(raw_recalled, max_items=5)
                # Query wider set for confidence calculation
                raw_conf = recall_for_confidence(
                    client=self.memory,
                    bank_id=target_bank,
                    vendor_slug=vendor_slug,
                    exception_type=match_result.exception_type,
                    limit=20,
                )
                confidence_sample = normalize_and_deduplicate_memories(raw_conf, max_items=15)
                # Retrieve cached vendor profile
                try:
                    prof = get_vendor_profile(
                        client=self.memory,
                        bank_id=target_bank,
                        vendor_slug=vendor_slug,
                        force_refresh=force_profile_refresh,
                    )
                    if prof and prof.summary:
                        profile_summary = prof.summary
                except Exception:
                    profile_summary = None

        # 2. EVALUATE POLICY–PRECEDENT CONFLICT
        conflict_eval = evaluate_policy_precedent_conflict(
            invoice=invoice,
            match_result=match_result,
            policy=governing_policy,
            historical_memories=recalled_mems if memory_enabled else [],
        )

        # 3. BUILD PROMPT & CALL GROQ LLM
        user_prompt = build_user_prompt(
            invoice=invoice,
            po=po,
            grn=grn,
            match_result=match_result,
            recalled_memories=recalled_mems,
            vendor_profile=profile_summary,
            memory_enabled=memory_enabled,
            policy=governing_policy,
            conflict_eval=conflict_eval,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        parsed_json, usage = self.llm.call_json(messages=messages, temperature=0.0)

        # 4. PARSE AND VALIDATE PROPOSED ACTION & AMOUNT
        raw_action = str(parsed_json.get("proposed_action", "ESCALATE")).upper()
        try:
            proposed_action = ApproverDecision(raw_action)
        except Exception:
            proposed_action = ApproverDecision.ESCALATED

        raw_amount = parsed_json.get("proposed_amount_inr", invoice.total_inr)
        try:
            proposed_amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        except Exception:
            proposed_amount = invoice.total_inr

        reasoning = str(parsed_json.get("reasoning", "Resolution proposed based on 3-way match reconciliation."))

        # 5. ENFORCE POLICY SUPREMACY OVER PRECEDENT
        # Written corporate policy strictly supersedes unauthorized historical approvals
        if enforce_policy_supremacy:
            if conflict_eval.status == ConflictStatus.POLICY_PRECEDENT_CONFLICT:
                if conflict_eval.recommended_action == ApproverDecision.REJECTED and proposed_action != ApproverDecision.REJECTED:
                    proposed_action = ApproverDecision.REJECTED
                    reasoning = (
                        f"[POLICY–PRECEDENT CONFLICT] {conflict_eval.explanation} "
                        f"Overriding recommendation to mandatory policy REJECTION."
                    )
                elif proposed_action == ApproverDecision.APPROVED and conflict_eval.recommended_action:
                    proposed_action = conflict_eval.recommended_action
                    reasoning = (
                        f"[POLICY–PRECEDENT CONFLICT] {conflict_eval.explanation} "
                        f"Overriding recommendation to {proposed_action.value}."
                    )
            elif conflict_eval.status == ConflictStatus.POLICY_VERSION_CHANGED:
                if conflict_eval.recommended_action:
                    proposed_action = conflict_eval.recommended_action
                    reasoning = (
                        f"[POLICY VERSION SHIFT] {conflict_eval.explanation} "
                        f"Governed by active standard {governing_policy.policy_id} v{governing_policy.version}."
                    )
            elif conflict_eval.status == ConflictStatus.POLICY_UNKNOWN:
                proposed_action = ApproverDecision.ESCALATED
                reasoning = f"[UNVERIFIED POLICY] {conflict_eval.explanation}"

        requires_escalation = conflict_eval.requires_escalation or (proposed_action == ApproverDecision.ESCALATED)

        # 6. FILTER CITATIONS (Prevent LLM hallucination of uncited memory IDs)
        valid_recalled_ids = {
            m.document_id for m in recalled_mems if m.document_id
        }.union({m.id for m in recalled_mems})

        raw_cited_ids = parsed_json.get("cited_memory_ids", [])
        if not isinstance(raw_cited_ids, list):
            raw_cited_ids = []

        validated_citations = [
            cid for cid in raw_cited_ids
            if cid in valid_recalled_ids
        ]

        # 7. DETERMINISTIC CONFIDENCE CALCULATION
        confidence = calculate_confidence(
            proposed_decision=proposed_action,
            historical_memories=confidence_sample if memory_enabled else [],
            expected_vendor_slug=vendor_slug if memory_enabled else None,
            expected_exception_type=match_result.exception_type if memory_enabled else None,
        )

        return ResolutionProposal(
            invoice_number=invoice.invoice_number,
            vendor_name=invoice.vendor_name,
            exception_type=match_result.exception_type,
            proposed_action=proposed_action,
            proposed_amount_inr=proposed_amount,
            reasoning=reasoning,
            cited_memory_ids=validated_citations,
            confidence=confidence,
            memory_enabled=memory_enabled,
            recalled_memories=recalled_mems,
            vendor_profile_summary=profile_summary,
            token_usage=usage,
            policy_id=governing_policy.policy_id if governing_policy else None,
            policy_version=governing_policy.version if governing_policy else None,
            policy_title=governing_policy.title if governing_policy else None,
            quoted_clause=governing_policy.primary_clause if governing_policy else None,
            conflict_status=conflict_eval.status,
            conflict_explanation=conflict_eval.explanation,
            requires_escalation=requires_escalation,
            escalation_path=conflict_eval.escalation_path or (governing_policy.authorized_escalation_path if governing_policy else "Finance Controller"),
        )

