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
from pydantic import BaseModel, Field

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from agent.confidence import calculate_confidence, ConfidenceScore
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
                seen_docs: set = set()
                combined_mems: List[RecalledMemory] = []
                for m in (demo_mems + baseline_mems):
                    doc_key = m.document_id or m.id
                    if doc_key not in seen_docs:
                        seen_docs.add(doc_key)
                        combined_mems.append(m)
                recalled_mems = combined_mems[:5]

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
                seen_conf_docs: set = set()
                combined_conf: List[RecalledMemory] = []
                for m in (demo_conf + baseline_conf):
                    doc_key = m.document_id or m.id
                    if doc_key not in seen_conf_docs:
                        seen_conf_docs.add(doc_key)
                        combined_conf.append(m)
                confidence_sample = combined_conf

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
                recalled_mems = recall_for_exception(
                    client=self.memory,
                    bank_id=target_bank,
                    invoice=invoice,
                    match_result=match_result,
                    limit=5,
                )
                # Query wider set for confidence calculation
                confidence_sample = recall_for_confidence(
                    client=self.memory,
                    bank_id=target_bank,
                    vendor_slug=vendor_slug,
                    exception_type=match_result.exception_type,
                    limit=15,
                )
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

