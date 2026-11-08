"""
agent/prompts.py
────────────────────────────────────────────────────────────────────────────────
Structured Prompt Templates for LedgerMind AP Exception Resolution.

Guarantees (Milestone 3.1):
  1. No invented policy claims (written company policy is explicitly marked as unintegrated).
  2. Clear distinction between deterministic matching math and corporate policy.
  3. Strict citation integrity: cites only actual recalled memory document IDs.
  4. Explicitly instructs that historical approvals are discretionary precedents, not binding financial authority.
"""

from typing import Any, List, Optional
from data.models import GoodsReceiptNote, Invoice, MatchResult, PurchaseOrder
from memory.schema import RecalledMemory
from policy.models import CompanyPolicy, ConflictStatus, PolicyConflictEvaluation

SYSTEM_PROMPT = """\
You are LedgerMind, an advisory AI assistant specializing in Indian Accounts-Payable (AP) exception analysis.

Your duty is to analyze deterministic 3-way match exceptions (Invoice vs Purchase Order vs Goods Receipt Note)
by comparing governing written corporate policy against historical precedents retrieved from Hindsight memory.

CORE PRINCIPLES & BOUNDARIES:
1. STRICT ADVISORY ROLE: You NEVER approve financial payments, execute disbursements, or authorize bank transactions. Your recommendation is strictly advisory for human review.
2. STATUTORY TAX INTEGRITY: Statutory GST rates (CGST/SGST/IGST) and HSN/SAC codes are strictly governed by Indian Law. Past approvals cannot override statutory tax obligations.
3. CORPORATE POLICY SUPREMACY: Applicable corporate written policies take strict precedence over past human precedent. Historical approvals stored in memory reflect past human discretionary decisions. They do NOT constitute binding authorization to violate written financial controls or policy limits.
4. POLICY–PRECEDENT CONFLICT HANDLING: When a conflict is detected between applicable written policy and historical human approvals (e.g. past approvers informally approved an overage that written policy strictly caps), you must HIGHLIGHT the conflict and recommend ESCALATED review rather than repeating the unauthorized practice.
5. CITATION INTEGRITY: If institutional memories are provided, cite ONLY the exact `document_id` of recalled memories you directly rely upon in `cited_memory_ids`. NEVER invent or fabricate document IDs.
6. POLICY CITATION INTEGRITY: Quote only the actual policy clause provided. If policy is unknown or unmapped, state that policy guidelines are unverified and recommend authorized human review.

OUTPUT FORMAT:
Respond with a single, valid JSON object strictly matching this schema:
{
  "proposed_action": "APPROVED" | "EDITED" | "REJECTED" | "ESCALATED",
  "proposed_amount_inr": <number>,
  "reasoning": "<thorough, factual explanation citing governing policy clauses, discrepancy figures, and recalled precedents>",
  "cited_memory_ids": ["<document_id>", ...]
}
Do NOT include markdown formatting outside JSON or conversational filler.
"""


def build_user_prompt(
    invoice: Invoice,
    po: PurchaseOrder,
    grn: Optional[GoodsReceiptNote],
    match_result: MatchResult,
    recalled_memories: List[RecalledMemory],
    vendor_profile: Optional[str] = None,
    memory_enabled: bool = True,
    policy: Optional[CompanyPolicy] = None,
    conflict_eval: Optional[PolicyConflictEvaluation] = None,
) -> str:
    """Construct the comprehensive context prompt for the LLM resolver."""
    lines: List[str] = []

    lines.append("══════════════════════════════════════════════════════════════════")
    lines.append("CURRENT INVOICE & MATCH RESULT (DETERMINISTIC RECONCILIATION)")
    lines.append("══════════════════════════════════════════════════════════════════")
    lines.append(f"Vendor Name:     {invoice.vendor_name}")
    lines.append(f"Vendor GSTIN:    {invoice.gstin}")
    lines.append(f"Invoice Number:  {invoice.invoice_number}")
    lines.append(f"Invoice Date:    {invoice.invoice_date}")
    lines.append(f"PO Number:       {po.po_number}")
    lines.append(f"PO Validity:     {po.issue_date} to {po.valid_until}")
    lines.append(f"GRN Number:      {grn.grn_number if grn else 'N/A (Pure Service Transaction)'}")
    lines.append(f"Billed Item:     {invoice.item_description}")
    lines.append(f"HSN Code:        Invoice: {invoice.hsn_code} vs PO: {po.hsn_code}")
    lines.append(f"Quantity:        Invoice: {invoice.quantity} vs PO: {po.quantity} vs GRN Accepted: {grn.accepted_quantity if grn else 'N/A'}")
    lines.append(f"Unit Price:      Invoice: ₹{invoice.unit_price_inr:,.2f} vs PO: ₹{po.unit_price_inr:,.2f}")
    lines.append(f"GST Rate:        Invoice: {invoice.gst_rate * 100:.1f}% vs PO: {po.gst_rate * 100:.1f}%")
    lines.append(f"Total Billed:    ₹{invoice.total_inr:,.2f} (PO Contracted: ₹{po.total_inr:,.2f})")
    lines.append(f"Primary Issue:   {match_result.exception_type.value}")
    lines.append(f"Match Summary:   {match_result.explanation}")

    if match_result.primary_discrepancy and match_result.primary_discrepancy.delta_inr:
        lines.append(f"Financial Delta: ₹{match_result.primary_discrepancy.delta_inr:+,.2f}")

    # POLICY RAG SECTION
    lines.append("\n══════════════════════════════════════════════════════════════════")
    lines.append("GOVERNING CORPORATE POLICY (POLICY RAG)")
    lines.append("══════════════════════════════════════════════════════════════════")
    if policy:
        lines.append(f"Policy ID:       {policy.policy_id} (Version {policy.version})")
        lines.append(f"Policy Title:    {policy.title}")
        lines.append(f"Effective From:  {policy.effective_from} {'to ' + str(policy.effective_to) if policy.effective_to else '(Current)'}")
        lines.append(f"Escalation Path: {policy.authorized_escalation_path}")
        lines.append(f"Primary Clause:\n\"{policy.primary_clause}\"\n")
        lines.append(f"Policy Directives:\n{policy.full_policy_text}")
    else:
        lines.append("Policy Status:   UNKNOWN / UNMAPPED (No governing corporate policy located).")
        lines.append("Directive:       Require authorized supervisor review.")

    if conflict_eval:
        lines.append("\n══════════════════════════════════════════════════════════════════")
        lines.append("POLICY–PRECEDENT CONFLICT EVALUATION")
        lines.append("══════════════════════════════════════════════════════════════════")
        lines.append(f"Conflict Status:     {conflict_eval.status.value}")
        lines.append(f"Conflict Finding:    {conflict_eval.explanation}")
        lines.append(f"Requires Escalation: {'YES' if conflict_eval.requires_escalation else 'NO'}")
        if conflict_eval.recommended_action:
            lines.append(f"Policy-Mandated Action Override: {conflict_eval.recommended_action.value}")

    if memory_enabled:
        lines.append("\n══════════════════════════════════════════════════════════════════")
        lines.append("INSTITUTIONAL MEMORY (RECALLED HISTORICAL DECISIONS)")
        lines.append("══════════════════════════════════════════════════════════════════")

        if vendor_profile:
            lines.append(f"Vendor Synthesis Profile:\n{vendor_profile}\n")

        if recalled_memories:
            lines.append(f"Found {len(recalled_memories)} past exception records in memory:\n")
            for idx, m in enumerate(recalled_memories, 1):
                doc_id = m.document_id or m.id
                date_str = m.occurred_start.strftime("%Y-%m-%d") if m.occurred_start else "Historical"
                score_str = f"relevance: {m.score:.2f}" if m.score is not None else "offline"
                lines.append(f"[{idx}] Document ID: {doc_id} ({date_str} | {score_str})")
                lines.append(f"Tags: {', '.join(m.tags)}")
                lines.append(f"Record:\n{m.text}")
                lines.append("──────────────────────────────────────────────────────────────────")
        else:
            lines.append("No past resolution records found for this vendor/exception in memory bank.")
    else:
        lines.append("\n══════════════════════════════════════════════════════════════════")
        lines.append("INSTITUTIONAL MEMORY: DISABLED (Zero Historical Context)")
        lines.append("══════════════════════════════════════════════════════════════════")
        lines.append(
            "Evaluate this invoice strictly on applicable written corporate policy and deterministic matching variance. "
            "Do NOT reference past resolutions."
        )

    lines.append("\nProvide your structured recommendation in valid JSON:")
    return "\n".join(lines)
