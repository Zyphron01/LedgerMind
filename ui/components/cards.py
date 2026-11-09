"""
ui/components/cards.py
────────────────────────────────────────────────────────────────────────────────
Premium Reusable UI Components and Cards for LedgerMind Streamlit App.
Provides structured styling for discrepancies, confidence scores, evidence cards,
policy intelligence, and system advisory notices inspired by Tremor and shadcn/ui.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
import streamlit as st

from agent.confidence import ConfidenceBand, ConfidenceScore
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, ExceptionType, MatchResult
from data.vendors import ALL_VENDORS, get_vendor_slug
from memory.schema import RecalledMemory


def render_advisory_banner() -> None:
    """Render mandatory non-execution compliance disclaimer with glassmorphic styling."""
    st.markdown(
        """
        <div class="lm-callout" style="border-left: 4px solid #3b82f6; background: rgba(30, 41, 59, 0.5); border-radius: 0 10px 10px 0; padding: 14px 18px; margin-bottom: 20px; display: flex; align-items: center; gap: 14px;">
            <div style="font-size: 1.4rem; line-height: 1;">🛡️</div>
            <div style="font-size: 0.86rem; color: #cbd5e1; line-height: 1.45;">
                <span style="font-weight: 700; color: #f8fafc; letter-spacing: 0.02em;">ADVISORY AP DECISION ENGINE:</span>
                LedgerMind assists Accounts Payable teams by recalling institutional precedents and generating auditable resolution recommendations.
                <span style="color: #93c5fd; font-weight: 600;">It never executes bank disbursements, modifies ERP general ledgers, or triggers fund transfers.</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_decision_badge(decision: ApproverDecision) -> str:
    """Return styled HTML badge for approver decision."""
    val = decision.value if hasattr(decision, "value") else str(decision)
    if val == ApproverDecision.APPROVED.value:
        return '<span class="lm-badge lm-badge-emerald">✓ APPROVED</span>'
    elif val == ApproverDecision.EDITED.value:
        return '<span class="lm-badge lm-badge-blue">✎ EDITED</span>'
    elif val == ApproverDecision.REJECTED.value:
        return '<span class="lm-badge lm-badge-rose">✕ REJECTED</span>'
    elif val == ApproverDecision.ESCALATED.value:
        return '<span class="lm-badge lm-badge-amber">⚠ ESCALATED</span>'
    return f'<span class="lm-badge lm-badge-gray">⚪ {val}</span>'


def render_discrepancy_banner(match_result: MatchResult) -> None:
    """Render structured 3-way match banner with Tremor callout aesthetics (green for match, red for exception)."""
    if match_result.is_match:
        st.markdown(
            f"""
            <div class="lm-callout lm-callout-success" style="margin-bottom: 18px; border-left: 4px solid #10b981; background: rgba(6, 78, 59, 0.35); padding: 14px 18px; border-radius: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 1.2rem;">✅</span>
                        <span style="font-weight: 700; color: #34d399; letter-spacing: 0.03em; font-size: 0.95rem;">THREE-WAY MATCH RECONCILED</span>
                    </div>
                    <span class="lm-badge lm-badge-emerald">CLEAN MATCH</span>
                </div>
                <div style="color: #e2e8f0; font-size: 0.92rem; margin-bottom: 12px; font-weight: 500;">
                    {match_result.explanation or "All billed line items, unit rates, quantities, and GST classifications reconcile with purchase order and warehouse logs."}
                </div>
                <div style="display: flex; gap: 20px; font-size: 0.84rem; color: #94a3b8; border-top: 1px solid rgba(16, 185, 129, 0.2); padding-top: 8px; flex-wrap: wrap;">
                    <div>Invoice Amount: <strong style="color: #f8fafc;">₹{match_result.invoice_amount_inr:,.2f}</strong></div>
                    <div>Contractual PO Total: <strong style="color: #f8fafc;">₹{match_result.expected_amount_inr:,.2f}</strong></div>
                    <div>Financial Variance: <strong style="color: #10b981;">₹0.00 (0.0%)</strong></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    exc_type = match_result.exception_type.value
    explanation = match_result.explanation
    variance = match_result.variance_inr

    var_color = "#ef4444" if variance != Decimal("0.00") else "#10b981"
    var_sign = "+" if variance > Decimal("0.00") else ""

    st.markdown(
        f"""
        <div class="lm-callout lm-callout-danger" style="margin-bottom: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.2rem;">⚠️</span>
                    <span style="font-weight: 700; color: #f87171; letter-spacing: 0.03em; font-size: 0.95rem;">3-WAY MATCH EXCEPTION DETECTED</span>
                </div>
                <span class="lm-badge lm-badge-rose">{exc_type}</span>
            </div>
            <div style="color: #e2e8f0; font-size: 0.92rem; margin-bottom: 12px; font-weight: 500;">
                {explanation}
            </div>
            <div style="display: flex; gap: 20px; font-size: 0.84rem; color: #94a3b8; border-top: 1px solid rgba(239, 68, 68, 0.2); padding-top: 8px; flex-wrap: wrap;">
                <div>Invoice Amount: <strong style="color: #f8fafc;">₹{match_result.invoice_amount_inr:,.2f}</strong></div>
                <div>Expected PO Total: <strong style="color: #f8fafc;">₹{match_result.expected_amount_inr:,.2f}</strong></div>
                <div>Financial Variance: <strong style="color: {var_color};">{var_sign}₹{abs(variance):,.2f}</strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_confidence_card(confidence: ConfidenceScore) -> None:
    """Render deterministic confidence score with interactive visual meter and decision breakdown."""
    score_pct = int(min(max(confidence.score, 0.0), 1.0) * 100)

    if confidence.band == ConfidenceBand.HIGH:
        band_badge = '<span class="lm-badge lm-badge-emerald">HIGH CONFIDENCE</span>'
        bar_class = "lm-progress-bar-high"
        band_accent = "#10b981"
    elif confidence.band == ConfidenceBand.MEDIUM:
        band_badge = '<span class="lm-badge lm-badge-amber">MEDIUM CONFIDENCE</span>'
        bar_class = "lm-progress-bar-med"
        band_accent = "#f59e0b"
    else:
        band_badge = '<span class="lm-badge lm-badge-rose">LOW CONFIDENCE</span>'
        bar_class = "lm-progress-bar-low"
        band_accent = "#ef4444"

    st.markdown(
        f"""
        <div class="lm-card" style="margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 1.1rem;">📊</span>
                    <span style="font-weight: 700; font-size: 1.05rem; color: #f8fafc;">Precedent-Grounded Heuristic Confidence</span>
                </div>
                <div>{band_badge}</div>
            </div>
            <div class="lm-progress-bg">
                <div class="{bar_class}" style="width: {score_pct}%;"></div>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #94a3b8; margin-bottom: 14px;">
                <span>Deterministic Score: <strong style="color: {band_accent}; font-size: 0.9rem;">{confidence.score:.2f}</strong> ({score_pct}%)</span>
                <span>Consistency Rate: <strong style="color: #f8fafc;">{confidence.consistency * 100:.0f}%</strong></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Heuristic Score", f"{confidence.score:.2f}")
    with col2:
        st.metric("Sample Size (n)", f"{confidence.sample_size_n}")
    with col3:
        st.metric("Agreed Precedents", f"{confidence.agreement_count}")
    with col4:
        st.metric("Agreement Ratio", f"{confidence.consistency * 100:.0f}%")

    with st.expander("🔍 Confidence Formula & Decision Breakdown", expanded=False):
        st.write(f"**Explanation:** {confidence.explanation}")
        if confidence.decision_breakdown:
            st.write("**Decisions by Type across Unique Documents:**")
            st.json(confidence.decision_breakdown)
        if confidence.supporting_document_ids:
            st.write(f"**Unique Supporting Document IDs ({len(confidence.supporting_document_ids)}):**")
            st.write(", ".join([f"`{doc_id}`" for doc_id in confidence.supporting_document_ids]))
        if confidence.excluded_memories_count > 0:
            st.caption(
                f"🛡️ *{confidence.excluded_memories_count} redundant facts, duplicate memories, or out-of-scope "
                "records were excluded from this score to prevent double-counting.*"
            )


def get_memory_vendor_info(mem: RecalledMemory) -> Tuple[str, str]:
    """
    Extract (vendor_display_name, vendor_slug) from memory metadata, tags, or text.
    """
    # 1. Authoritative metadata
    if mem.metadata.get("vendor_name"):
        v_name = str(mem.metadata["vendor_name"]).strip()
        return v_name, get_vendor_slug(v_name)

    # 2. Authoritative tags
    for t in mem.tags:
        if t.startswith("vendor:"):
            v_slug = t.split(":", 1)[1].strip().lower()
            for v in ALL_VENDORS:
                if v.slug == v_slug:
                    return v.name, v.slug
            return v_slug.replace("-", " ").title(), v_slug

    # 3. Known vendor matching from narrative text
    for v in ALL_VENDORS:
        if v.name.lower() in mem.text.lower() or v.slug in mem.text.lower():
            return v.name, v.slug

    if "zenith" in mem.text.lower():
        return "Zenith Precision Engineering Pvt Ltd", "zenith-precision-engineering"

    return "Institutional AP Precedent", "institutional-precedent"


def render_evidence_memories(
    memories: List[RecalledMemory],
    target_vendor_name: Optional[str] = None,
) -> None:
    """Render recalled institutional memory facts with verified vendor attribution, cross-vendor disclosure, and Bento card aesthetics."""
    if not memories:
        st.info("No historical memories were recalled for this query.")
        return

    target_slug = get_vendor_slug(target_vendor_name) if target_vendor_name else None

    st.markdown(
        f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin: 18px 0 10px 0;">
            <div style="font-weight: 700; font-size: 1.05rem; color: #f8fafc; display: flex; align-items: center; gap: 8px;">
                <span>🧠</span> Recalled Precedents & Evidentiary Citations ({len(memories)})
            </div>
            <span class="lm-badge lm-badge-violet">Deduplicated Precedents</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for idx, mem in enumerate(memories, 1):
        doc = mem.document_id or mem.id[:12]
        is_feedback = "feedback" in (doc.lower() + "".join(mem.tags).lower())
        bank = mem.bank_id or (LIVE_DEMO_BANK_ID if is_feedback else BASELINE_EVAL_BANK_ID)

        # Bank badge
        if bank == LIVE_DEMO_BANK_ID or is_feedback:
            bank_badge = '<span class="lm-badge lm-badge-amber">🟡 LIVE DEMO BANK (Human Feedback)</span>'
        else:
            bank_badge = '<span class="lm-badge lm-badge-blue">🔵 BASELINE EVAL BANK (Historical Benchmark)</span>'

        # Memory vendor attribution
        mem_vendor_name, mem_vendor_slug = get_memory_vendor_info(mem)
        is_cross_vendor = bool(target_slug and mem_vendor_slug and mem_vendor_slug != target_slug)

        if is_cross_vendor:
            vendor_badge = (
                f'<span class="lm-badge lm-badge-amber" style="background: rgba(245, 158, 11, 0.18); '
                f'border: 1px solid rgba(245, 158, 11, 0.45); color: #fde68a; font-weight: 600;">'
                f'🟠 Cross-Vendor Precedent: {mem_vendor_name}</span>'
            )
        else:
            vendor_badge = (
                f'<span class="lm-badge lm-badge-blue" style="background: rgba(59, 130, 246, 0.12); '
                f'border: 1px solid rgba(59, 130, 246, 0.35); color: #bfdbfe;">'
                f'🏢 {mem_vendor_name}</span>'
            )

        storage_type = "💾 Offline JSONL Fallback" if mem.is_offline_fallback else "🧠 Hindsight Vector DB"
        score_str = f"Relevance: {mem.score:.2f}" if mem.score is not None else "Keyword Match"

        # Sanitize and ensure accurate tags belonging to this memory
        display_tags: List[str] = []
        has_vendor_tag = False
        for t in mem.tags:
            if t.startswith("vendor:"):
                # Always show the true vendor slug, never an incorrect one
                if not has_vendor_tag:
                    display_tags.append(f"vendor:{mem_vendor_slug}")
                    has_vendor_tag = True
            else:
                display_tags.append(t)
        if not has_vendor_tag and mem_vendor_slug:
            display_tags.insert(0, f"vendor:{mem_vendor_slug}")

        tag_pills = " ".join([
            f'<span class="lm-badge lm-badge-gray" style="font-size: 0.72rem; margin-right: 4px;">#{t}</span>'
            for t in display_tags[:6]
        ])

        st.markdown(
            f"""
            <div class="lm-card" style="padding: 16px 20px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                        <span style="font-weight: 700; color: #94a3b8; font-size: 0.85rem;">#{idx}</span>
                        <code style="color: #60a5fa; background: rgba(59, 130, 246, 0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.85rem;">{doc}</code>
                        {bank_badge}
                        {vendor_badge}
                    </div>
                    <div style="font-size: 0.78rem; color: #94a3b8;">
                        {storage_type} • <strong style="color: #cbd5e1;">{score_str}</strong>
                    </div>
                </div>
                <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.5; margin-bottom: 8px;">
                    {mem.text}
                </div>
                <div>{tag_pills}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_policy_intelligence_card(proposal: Any) -> None:
    """Render governing corporate policy, quoted clause, and conflict evaluation."""
    status_val = proposal.conflict_status.value if hasattr(proposal.conflict_status, "value") else str(proposal.conflict_status)

    if status_val == "COMPLIANT_PRECEDENT":
        status_badge = '<span class="lm-badge lm-badge-emerald">✓ COMPLIANT PRECEDENT</span>'
        callout_class = "lm-callout-success"
    elif status_val == "POLICY_PRECEDENT_CONFLICT":
        status_badge = '<span class="lm-badge lm-badge-rose">⚠ POLICY–PRECEDENT CONFLICT</span>'
        callout_class = "lm-callout-danger"
    elif status_val == "POLICY_VERSION_CHANGED":
        status_badge = '<span class="lm-badge lm-badge-amber">⚡ POLICY VERSION CHANGED</span>'
        callout_class = "lm-callout-warning"
    else:
        status_badge = f'<span class="lm-badge lm-badge-gray">⚪ {status_val}</span>'
        callout_class = "lm-callout-policy"

    policy_id_str = proposal.policy_id or "UNKNOWN"
    policy_ver_str = f"v{proposal.policy_version}" if proposal.policy_version else "N/A"
    policy_title_str = proposal.policy_title or "Unmapped Corporate Standard"

    st.markdown(
        f"""
        <div class="lm-callout {callout_class}" style="margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 1.2rem;">📜</span>
                    <span style="font-weight: 700; color: #f8fafc; font-size: 0.95rem;">
                        Governing Policy: <code style="color: #c084fc; background: rgba(139, 92, 246, 0.1); padding: 2px 6px; border-radius: 4px;">{policy_id_str} ({policy_ver_str})</code>
                    </span>
                    <span style="color: #94a3b8; font-size: 0.9rem;">— {policy_title_str}</span>
                </div>
                <div>{status_badge}</div>
            </div>
            {"<div style='background: rgba(15, 23, 42, 0.6); border-left: 3px solid #8b5cf6; padding: 10px 14px; margin: 10px 0; border-radius: 0 6px 6px 0; font-size: 0.88rem; color: #cbd5e1; font-style: italic;'><span style='color: #a78bfa; font-weight: 600; font-style: normal;'>Authoritative Directive:</span> &ldquo;" + proposal.quoted_clause + "&rdquo;</div>" if proposal.quoted_clause else ""}
            {f"<div style='font-size: 0.86rem; color: #fca5a5; margin-top: 8px; font-weight: 500;'><strong>⚠️ Conflict Finding:</strong> {proposal.conflict_explanation} &nbsp;|&nbsp; <strong>Escalation Path:</strong> <code>{proposal.escalation_path or 'Finance Controller'}</code></div>" if status_val == 'POLICY_PRECEDENT_CONFLICT' and proposal.conflict_explanation else ""}
            {f"<div style='font-size: 0.86rem; color: #fde68a; margin-top: 8px; font-weight: 500;'><strong>📌 Version Shift Finding:</strong> {proposal.conflict_explanation} &nbsp;|&nbsp; <strong>Escalation Path:</strong> <code>{proposal.escalation_path or 'Chief Financial Officer (CFO)'}</code></div>" if status_val == 'POLICY_VERSION_CHANGED' and proposal.conflict_explanation else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )
