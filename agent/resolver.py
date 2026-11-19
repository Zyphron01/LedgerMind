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
from agent.llm import GroqClient, LLMError
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from data.models import ApproverDecision, ExceptionType, GoodsReceiptNote, Invoice, MatchResult, PurchaseOrder
from data.vendors import get_vendor_slug
from memory.client import MemoryClient
from memory.operations import get_vendor_profile, recall_for_confidence, recall_for_exception
from memory.schema import RecalledMemory
from policy.conflict import evaluate_policy_precedent_conflict
from policy.models import CompanyPolicy, ConflictStatus, PolicyConflictEvaluation
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
    prior_audit_reviews: List[RecalledMemory] = Field(default_factory=list, description="Historical reviews of the current invoice preserved for audit traceability but excluded from precedent scoring")
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

    # Offline & LLM Resiliency (Milestone 2)
    llm_fallback: bool = False
    fallback_reason: Optional[str] = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Any) -> Any:
        if hasattr(v, "model_dump"):
            return v.model_dump()
        return v

    @field_validator("recalled_memories", "prior_audit_reviews", mode="before")
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
    exclude_invoice_number: Optional[str] = None,
    return_self_reviews: bool = False,
) -> Any:
    """
    Groups recalled memory facts by originating source review/document into
    a single logical evidence entry per historical precedent.
    Aggregates extracted sub-facts/observations under the primary entry in supporting_facts,
    preventing any single invoice review from consuming multiple display slots.
    Facts lacking reliable document attribution are labeled as ungrouped facts.

    If exclude_invoice_number is provided:
      Excludes self-referential reviews of the current invoice from the precedent list
      to prevent circular confidence inflation and evidence contamination.
      If return_self_reviews=True, returns (independent_precedents, self_reviews).
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
    self_review_entries: List[RecalledMemory] = []
    inv_clean = exclude_invoice_number.strip().upper() if exclude_invoice_number else None

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

        # Check if this group is a review of the current invoice being evaluated
        is_self = False
        if inv_clean:
            doc_upper = doc_id.upper()
            if doc_upper in (f"FEEDBACK-{inv_clean}", f"DECISION-{inv_clean}"):
                is_self = True
            elif str(primary.metadata.get("invoice_number", "")).strip().upper() == inv_clean:
                is_self = True
            elif f"FEEDBACK-{inv_clean}" in primary.text.upper() or f"INVOICE {inv_clean}" in primary.text.upper():
                is_self = True

        if is_self:
            self_review_entries.append(primary)
        else:
            logical_entries.append(primary)

    # 2. Append ungrouped facts only if remaining display slots exist
    for u in ungrouped_facts:
        if len(logical_entries) >= max_items:
            break
        if inv_clean and inv_clean in u.text.upper():
            continue
        u.supporting_facts = []
        logical_entries.append(u)

    selected = logical_entries[:max_items]
    if return_self_reviews:
        return selected, self_review_entries
    return selected


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

    def _generate_deterministic_fallback(
        self,
        invoice: Invoice,
        po: Optional[PurchaseOrder],
        grn: Optional[GoodsReceiptNote],
        match_result: MatchResult,
        conflict_eval: PolicyConflictEvaluation,
        recalled_memories: List[RecalledMemory],
        governing_policy: Optional[CompanyPolicy],
    ) -> Dict[str, Any]:
        """
        Deterministic, policy-grounded fallback resolution generator.
        Activates when Groq LLM is unavailable, offline, rate-limited, or raises LLMError.
        Reconciles 3-way match exceptions and corporate policy directives deterministically.
        """
        cited_ids: List[str] = []
        for m in recalled_memories[:3]:
            cid = m.document_id or m.id
            if cid:
                cited_ids.append(cid)

        # 0. Missing Purchase Order documentation (Incomplete Invoice)
        if po is None or getattr(invoice, "is_incomplete", False) or "pending po documentation" in (match_result.explanation or "").lower():
            return {
                "proposed_action": ApproverDecision.ESCALATED.value,
                "proposed_amount_inr": str(invoice.total_inr),
                "reasoning": f"[DETERMINISTIC FALLBACK] Missing purchase order documentation for invoice {invoice.invoice_number}. Invoice is marked incomplete; procurement escalation required.",
                "cited_memory_ids": cited_ids,
            }

        # 1. Clean match
        if match_result.is_match:
            return {
                "proposed_action": ApproverDecision.APPROVED.value,
                "proposed_amount_inr": str(invoice.total_inr),
                "reasoning": "Deterministic Fallback: Clean three-way match verified. Zero variances detected between invoice, PO, and GRN.",
                "cited_memory_ids": [],
            }

        # 2. Policy-precedent conflict or policy version shift: Corporate policy takes absolute supremacy
        if conflict_eval.status in (ConflictStatus.POLICY_PRECEDENT_CONFLICT, ConflictStatus.POLICY_VERSION_CHANGED):
            rec_action = conflict_eval.recommended_action or ApproverDecision.ESCALATED
            if rec_action == ApproverDecision.REJECTED:
                rec_amount = Decimal("0.00")
            elif match_result.expected_amount_inr is not None:
                rec_amount = match_result.expected_amount_inr
            else:
                rec_amount = invoice.total_inr

            return {
                "proposed_action": rec_action.value,
                "proposed_amount_inr": str(rec_amount),
                "reasoning": f"[DETERMINISTIC POLICY FALLBACK] {conflict_eval.explanation}. Corporate policy supersedes precedent.",
                "cited_memory_ids": cited_ids,
            }

        # 3. Duplicate invoice
        if match_result.exception_type == ExceptionType.DUPLICATE_INVOICE:
            return {
                "proposed_action": ApproverDecision.REJECTED.value,
                "proposed_amount_inr": "0.00",
                "reasoning": f"[DETERMINISTIC FALLBACK] Duplicate invoice detected ({match_result.explanation}). Automated rejection mandated to prevent duplicate disbursement.",
                "cited_memory_ids": cited_ids,
            }

        # 4. Expired Purchase Order
        if match_result.exception_type == ExceptionType.PO_EXPIRED:
            return {
                "proposed_action": ApproverDecision.REJECTED.value,
                "proposed_amount_inr": "0.00",
                "reasoning": f"[DETERMINISTIC FALLBACK] Purchase order validity expired ({match_result.explanation}). Automated rejection mandated per procurement policy.",
                "cited_memory_ids": cited_ids,
            }

        # 5. HSN mismatch (Statutory Tax Compliance)
        if match_result.exception_type == ExceptionType.HSN_MISMATCH:
            return {
                "proposed_action": ApproverDecision.REJECTED.value,
                "proposed_amount_inr": "0.00",
                "reasoning": f"[DETERMINISTIC FALLBACK] Statutory GST HSN code discrepancy detected ({match_result.explanation}). Statutory tax integrity requires rejection and vendor re-billing.",
                "cited_memory_ids": cited_ids,
            }

        # 6. GST Rate Error (Statutory Tax Compliance)
        if match_result.exception_type == ExceptionType.GST_RATE_ERROR:
            return {
                "proposed_action": ApproverDecision.REJECTED.value,
                "proposed_amount_inr": "0.00",
                "reasoning": f"[DETERMINISTIC FALLBACK] Statutory GST tax rate mismatch detected ({match_result.explanation}). Non-compliant tax rates mandate rejection.",
                "cited_memory_ids": cited_ids,
            }

        # 7. Quantity Shortfall
        if match_result.exception_type == ExceptionType.QUANTITY_SHORTFALL:
            if grn and getattr(grn, "accepted_quantity", 0) > 0 and match_result.expected_amount_inr:
                return {
                    "proposed_action": ApproverDecision.EDITED.value,
                    "proposed_amount_inr": str(match_result.expected_amount_inr),
                    "reasoning": f"[DETERMINISTIC FALLBACK] Quantity shortfall detected ({match_result.explanation}). Proposing adjustment to pay only for physical goods received (₹{match_result.expected_amount_inr:,.2f}) per GRN {grn.grn_number}.",
                    "cited_memory_ids": cited_ids,
                }
            return {
                "proposed_action": ApproverDecision.ESCALATED.value,
                "proposed_amount_inr": str(invoice.total_inr),
                "reasoning": f"[DETERMINISTIC FALLBACK] Quantity shortfall detected ({match_result.explanation}). Receiving verification requires procurement escalation.",
                "cited_memory_ids": cited_ids,
            }

        # 8. Price Mismatch
        if match_result.exception_type == ExceptionType.PRICE_MISMATCH:
            # Check if precedent supports EDITED to contracted PO price
            has_edit_precedent = any(
                str(getattr(m, "metadata", {}).get("decision", "")).upper() == "EDITED"
                for m in recalled_memories
            )
            if has_edit_precedent and match_result.expected_amount_inr:
                return {
                    "proposed_action": ApproverDecision.EDITED.value,
                    "proposed_amount_inr": str(match_result.expected_amount_inr),
                    "reasoning": f"[DETERMINISTIC FALLBACK] Unit price variance ({match_result.explanation}). Proposing adjustment to contracted PO unit price (₹{match_result.expected_amount_inr:,.2f}) per institutional precedent.",
                    "cited_memory_ids": cited_ids,
                }
            # Fallback to PO contracted price if expected amount exists
            if match_result.expected_amount_inr:
                return {
                    "proposed_action": ApproverDecision.EDITED.value,
                    "proposed_amount_inr": str(match_result.expected_amount_inr),
                    "reasoning": f"[DETERMINISTIC FALLBACK] Unit price variance ({match_result.explanation}). Proposing adjustment to contracted PO price (₹{match_result.expected_amount_inr:,.2f}).",
                    "cited_memory_ids": cited_ids,
                }
            return {
                "proposed_action": ApproverDecision.REJECTED.value,
                "proposed_amount_inr": "0.00",
                "reasoning": f"[DETERMINISTIC FALLBACK] Unit price variance ({match_result.explanation}) exceeds tolerance without authorized waiver. Mandating rejection.",
                "cited_memory_ids": cited_ids,
            }

        # 9. Default Fallback: Escalate
        return {
            "proposed_action": ApproverDecision.ESCALATED.value,
            "proposed_amount_inr": str(invoice.total_inr),
            "reasoning": f"[DETERMINISTIC FALLBACK] AP exception ({match_result.explanation}) requires human approver resolution.",
            "cited_memory_ids": cited_ids,
        }

    def resolve(
        self,
        invoice: Invoice,
        po: Optional[PurchaseOrder] = None,
        grn: Optional[GoodsReceiptNote] = None,
        match_result: Optional[MatchResult] = None,
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
        if match_result is None:
            from agent.matcher import match_invoice
            match_result = match_invoice(invoice, po, grn)
        vendor_slug = get_vendor_slug(invoice.vendor_name)
        recalled_mems: List[RecalledMemory] = []
        prior_audit_reviews: List[RecalledMemory] = []
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
                # Combine with newly retained live feedback prioritized first, strictly excluding self-reviews
                recalled_mems, self_reviews = normalize_and_deduplicate_memories(
                    demo_mems + baseline_mems,
                    max_items=5,
                    exclude_invoice_number=invoice.invoice_number,
                    return_self_reviews=True,
                )
                prior_audit_reviews.extend(self_reviews)

                # Confidence sample combining both live demo feedback and baseline precedents (excluding self-reviews)
                demo_conf = recall_for_confidence(
                    client=self.memory,
                    bank_id=LIVE_DEMO_BANK_ID,
                    vendor_slug=vendor_slug,
                    exception_type=match_result.exception_type,
                    limit=15,
                    vendor_name=invoice.vendor_name,
                )
                baseline_conf = recall_for_confidence(
                    client=self.memory,
                    bank_id=BASELINE_EVAL_BANK_ID,
                    vendor_slug=vendor_slug,
                    exception_type=match_result.exception_type,
                    limit=15,
                    vendor_name=invoice.vendor_name,
                )
                confidence_sample, self_conf_reviews = normalize_and_deduplicate_memories(
                    demo_conf + baseline_conf,
                    max_items=15,
                    exclude_invoice_number=invoice.invoice_number,
                    return_self_reviews=True,
                )
                for sr in self_conf_reviews:
                    if not any(ar.document_id == sr.document_id for ar in prior_audit_reviews):
                        prior_audit_reviews.append(sr)

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
                recalled_mems, self_reviews = normalize_and_deduplicate_memories(
                    raw_recalled,
                    max_items=5,
                    exclude_invoice_number=invoice.invoice_number,
                    return_self_reviews=True,
                )
                prior_audit_reviews.extend(self_reviews)

                # Query wider set for confidence calculation
                raw_conf = recall_for_confidence(
                    client=self.memory,
                    bank_id=target_bank,
                    vendor_slug=vendor_slug,
                    exception_type=match_result.exception_type,
                    limit=20,
                    vendor_name=invoice.vendor_name,
                )
                confidence_sample, _ = normalize_and_deduplicate_memories(
                    raw_conf,
                    max_items=15,
                    exclude_invoice_number=invoice.invoice_number,
                    return_self_reviews=True,
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

        # 3. BUILD PROMPT & CALL GROQ LLM (WITH RESILIENT DETERMINISTIC FALLBACK)
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

        is_llm_fallback = False
        llm_fallback_reason: Optional[str] = None
        parsed_json: Dict[str, Any] = {}
        usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        is_llm_usable = False
        if self.llm:
            if hasattr(self.llm, "is_available") and callable(self.llm.is_available):
                is_llm_usable = self.llm.is_available()
            elif hasattr(self.llm, "call_json"):
                is_llm_usable = True

        try:
            if not is_llm_usable:
                raise LLMError("Groq client unavailable: GROQ_API_KEY is not configured or client is uninitialized.")
            parsed_json, usage = self.llm.call_json(messages=messages, temperature=0.0)
        except Exception as e:
            is_llm_fallback = True
            llm_fallback_reason = f"{type(e).__name__}: {e}"
            parsed_json = self._generate_deterministic_fallback(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_result,
                conflict_eval=conflict_eval,
                recalled_memories=recalled_mems,
                governing_policy=governing_policy,
            )

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
                if po is None or getattr(invoice, "is_incomplete", False):
                    reasoning = f"[DETERMINISTIC FALLBACK] Missing purchase order documentation for invoice {invoice.invoice_number}. Invoice is marked incomplete; procurement escalation required."
                else:
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
            current_invoice_number=invoice.invoice_number if memory_enabled else None,
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
            prior_audit_reviews=prior_audit_reviews,
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
            llm_fallback=is_llm_fallback,
            fallback_reason=llm_fallback_reason,
        )

