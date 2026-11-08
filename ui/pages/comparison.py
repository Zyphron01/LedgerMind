"""
ui/pages/comparison.py
────────────────────────────────────────────────────────────────────────────────
View D (Task 3): Side-by-Side Memory OFF vs Memory ON Comparative Evaluation.
Runs the same held-out invoice through zero-context baseline (Memory OFF) and
precedent-grounded mode (Memory ON) to demonstrate empirical confidence uplift
and evidentiary audit trails without fabricating artificial action differences.
"""

from decimal import Decimal
import streamlit as st

from agent.resolver import ResolutionAgent, ResolutionProposal
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import HeldOutInvoice
from ui.components.cards import (
    render_advisory_banner,
    render_confidence_card,
    render_decision_badge,
    render_discrepancy_banner,
    render_evidence_memories,
)
from ui.state import (
    get_held_out_by_id,
    get_held_out_invoices,
    get_resolution_agent,
)


def render_comparison_page() -> None:
    """Render side-by-side Memory OFF vs Memory ON evaluation view."""
    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em;">
                    Memory OFF vs ON Comparative Evaluation
                </h1>
                <span class="lm-badge lm-badge-violet">A/B Discrepancy Analysis</span>
            </div>
            <p style="color: #94a3b8; font-size: 1rem; margin-top: 6px; line-height: 1.5;">
                Directly evaluate the impact of institutional memory by executing the exact same AP exception through two operational modes: <strong>Zero-Context Baseline (Memory OFF)</strong> and <strong>Precedent-Grounded (Memory ON)</strong>.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_advisory_banner()

    held_out = get_held_out_invoices()
    available_ids = [inv.invoice.invoice_number for inv in held_out]

    current_selected = st.session_state.get("selected_invoice_id", available_ids[0])
    if current_selected not in available_ids:
        current_selected = available_ids[0]

    # TOP CONTROL PANEL
    with st.container():
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 18px 20px 8px 20px; margin-bottom: 18px;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 10px; display: flex; align-items: center; gap: 8px;">
                    <span>⚖️</span> Select Benchmark Case for Evaluation
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_sel, col_btn = st.columns([3, 1])
        with col_sel:
            selected_id = st.selectbox(
                "Select Benchmark Invoice to Compare:",
                available_ids,
                index=available_ids.index(current_selected),
                format_func=lambda x: f"{x} — {next(i.invoice.vendor_name for i in held_out if i.invoice.invoice_number == x)} ({next(i.match_result.exception_type.value for i in held_out if i.invoice.invoice_number == x)})",
            )
            st.session_state["selected_invoice_id"] = selected_id

        with col_btn:
            st.write("")
            st.write("")
            run_comp = st.button("🔄 Run Comparative Analysis", type="primary", use_container_width=True)

    target_held_out: HeldOutInvoice = get_held_out_by_id(selected_id)
    inv = target_held_out.invoice
    po = target_held_out.po
    grn = target_held_out.grn
    match_res = target_held_out.match_result

    render_discrepancy_banner(match_res)

    comparison_cache = st.session_state.setdefault("comparison_cache", {})
    agent = get_resolution_agent()

    if run_comp:
        with st.spinner("Executing Memory OFF (Zero Context) and Memory ON (Hindsight Recall)..."):
            try:
                # 1. Memory OFF
                prop_off = agent.resolve(
                    invoice=inv,
                    po=po,
                    grn=grn,
                    match_result=match_res,
                    memory_enabled=False,
                )
                # 2. Memory ON
                prop_on = agent.resolve(
                    invoice=inv,
                    po=po,
                    grn=grn,
                    match_result=match_res,
                    memory_enabled=True,
                    bank_id=LIVE_DEMO_BANK_ID,
                )
                comparison_cache[selected_id] = (prop_off, prop_on)
            except Exception as e:
                st.error(f"Comparative run failed: {e}")
                return

    cached_results = comparison_cache.get(selected_id)
    if not cached_results:
        st.info("👆 Click **'Run Comparative Analysis'** above to execute both modes side-by-side on this invoice.")
        return

    prop_off, prop_on = cached_results

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # SIDE-BY-SIDE DUAL CARDS (21st.dev style)
    col_left, col_right = st.columns(2)

    # ─── LEFT COLUMN: MEMORY OFF ──────────────────────────────────────────────
    with col_left:
        st.markdown(
            f"""
            <div class="lm-card" style="border-top: 3px solid #6b7280; height: 100%;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.2rem;">🚫</span>
                        <span style="font-weight: 700; font-size: 1.05rem; color: #f8fafc;">Memory OFF (Baseline)</span>
                    </div>
                    <span class="lm-badge lm-badge-gray">Zero-Context</span>
                </div>
                <div style="font-size: 0.84rem; color: #94a3b8; margin-bottom: 14px;">
                    Governed by written corporate policy and contract arithmetic only. No past human decisions or supplier history accessible.
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.88rem; color: #cbd5e1; margin-bottom: 16px;">
                    <div>• <strong>Governing Policy:</strong> <code style="color: #cbd5e1;">{prop_off.policy_id or 'UNKNOWN'} v{prop_off.policy_version or 'N/A'}</code></div>
                    <div>• <strong>Policy State:</strong> <code style="color: #94a3b8;">{prop_off.conflict_status.value}</code></div>
                    <div>• <strong>Proposed Action:</strong> {render_decision_badge(prop_off.proposed_action)}</div>
                    <div>• <strong>Adjusted Amount:</strong> <strong style="color: #f8fafc; font-size: 1rem;">₹{prop_off.proposed_amount_inr:,.2f}</strong></div>
                    <div>• <strong>Confidence Score:</strong> <span class="lm-badge lm-badge-rose">{prop_off.confidence.score:.2f} (LOW)</span></div>
                    <div>• <strong>Sample Size (n):</strong> <code>0 unique precedents</code></div>
                    <div>• <strong>Requires Escalation:</strong> <code>{'YES' if prop_off.requires_escalation else 'NO'}</code></div>
                </div>
                <div style="background: rgba(15, 23, 42, 0.6); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                    <div style="font-size: 0.8rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px;">Agent Reasoning:</div>
                    <div style="font-size: 0.88rem; color: #e2e8f0; line-height: 1.5;">{prop_off.reasoning}</div>
                </div>
                <div style="font-size: 0.8rem; color: #64748b;">
                    Precedent Citations: <em>None (Memory disabled)</em>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ─── RIGHT COLUMN: MEMORY ON ─────────────────────────────────────────────
    with col_right:
        st.markdown(
            f"""
            <div class="lm-card" style="border-top: 3px solid #10b981; height: 100%; box-shadow: 0 0 20px -5px rgba(16, 185, 129, 0.15);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.2rem;">🧠</span>
                        <span style="font-weight: 700; font-size: 1.05rem; color: #f8fafc;">Memory ON (Precedent-Grounded)</span>
                    </div>
                    <span class="lm-badge lm-badge-emerald">Hindsight Active</span>
                </div>
                <div style="font-size: 0.84rem; color: #94a3b8; margin-bottom: 14px;">
                    Active dual reconciliation: compares written policy against empirical human approvals retrieved through Hindsight.
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.88rem; color: #cbd5e1; margin-bottom: 16px;">
                    <div>• <strong>Governing Policy:</strong> <code style="color: #c084fc;">{prop_on.policy_id or 'UNKNOWN'} v{prop_on.policy_version or 'N/A'}</code></div>
                    <div>• <strong>Policy State:</strong> <code style="color: #34d399;">{prop_on.conflict_status.value}</code></div>
                    <div>• <strong>Proposed Action:</strong> {render_decision_badge(prop_on.proposed_action)}</div>
                    <div>• <strong>Adjusted Amount:</strong> <strong style="color: #f8fafc; font-size: 1rem;">₹{prop_on.proposed_amount_inr:,.2f}</strong></div>
                    <div>• <strong>Confidence Score:</strong> <span class="lm-badge {'lm-badge-emerald' if prop_on.confidence.score >= 0.75 else 'lm-badge-amber'}">{prop_on.confidence.score:.2f} ({prop_on.confidence.band.value})</span></div>
                    <div>• <strong>Sample Size (n):</strong> <strong style="color: #34d399;">{prop_on.confidence.sample_size_n} unique precedents</strong></div>
                    <div>• <strong>Requires Escalation:</strong> <code>{'YES' if prop_on.requires_escalation else 'NO'}</code></div>
                </div>
                <div style="background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                    <div style="font-size: 0.8rem; font-weight: 700; color: #34d399; text-transform: uppercase; margin-bottom: 6px;">Agent Reasoning & Precedent Reconciliation:</div>
                    <div style="font-size: 0.88rem; color: #e2e8f0; line-height: 1.5;">{prop_on.reasoning}</div>
                </div>
                <div style="font-size: 0.8rem; color: #94a3b8;">
                    Precedent Citations: <strong style="color: #60a5fa;">{', '.join(prop_on.cited_memory_ids) if prop_on.cited_memory_ids else 'None'}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # ─── COMPARATIVE TAKEAWAY CALLOUT ────────────────────────────────────────
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
            <span>💡</span> Analytical Takeaway & Evidentiary Value
        </div>
        """,
        unsafe_allow_html=True,
    )

    same_action = prop_off.proposed_action == prop_on.proposed_action
    same_amount = prop_off.proposed_amount_inr == prop_on.proposed_amount_inr

    with st.container():
        if same_action and same_amount:
            st.markdown(
                f"""
                <div class="lm-callout lm-callout-success" style="margin-bottom: 16px;">
                    <div style="font-weight: 700; font-size: 1rem; color: #f8fafc; margin-bottom: 8px;">
                        Convergence in Math, Divergence in Institutional Authority
                    </div>
                    <div style="color: #cbd5e1; font-size: 0.9rem; line-height: 1.6;">
                        Both modes arrived at the identical financial resolution: <strong>{prop_on.proposed_action.value}</strong> at <strong>₹{prop_on.proposed_amount_inr:,.2f}</strong>. This is standard and expected when contractual PO terms dictate unit prices or delivered quantities.
                    </div>
                    <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(16, 185, 129, 0.2); font-size: 0.88rem; color: #cbd5e1; display: flex; flex-direction: column; gap: 6px;">
                        <div><strong>1. Evidentiary Grounding:</strong> Memory OFF operates in a vacuum with <strong>0.00 confidence (LOW)</strong>. Memory ON elevates confidence to <strong>{prop_on.confidence.score:.2f} ({prop_on.confidence.band.value})</strong> by verifying that past human approvers consistently reached this outcome across <strong>{prop_on.confidence.sample_size_n} unique historical decisions</strong>.</div>
                        <div><strong>2. Audit Defensibility:</strong> Memory ON cites specific document IDs (<code style="color: #60a5fa;">{', '.join(prop_on.cited_memory_ids)}</code>), providing internal auditors and controllers with an immediate, traceable precedent trail.</div>
                        <div><strong>3. Vendor Behavioral Quirks:</strong> Memory ON recognizes supplier-specific patterns without treating standard industry quirks as adversarial fraud attempts.</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div class="lm-callout lm-callout-warning" style="margin-bottom: 16px;">
                    <div style="font-weight: 700; font-size: 1rem; color: #f8fafc; margin-bottom: 8px;">
                        Behavioral Shift Driven by Institutional Precedent
                    </div>
                    <div style="color: #cbd5e1; font-size: 0.9rem; line-height: 1.6;">
                        • Memory OFF Proposed: <strong>{prop_off.proposed_action.value}</strong> (₹{prop_off.proposed_amount_inr:,.2f})<br>
                        • Memory ON Proposed: <strong>{prop_on.proposed_action.value}</strong> (₹{prop_on.proposed_amount_inr:,.2f})<br><br>
                        Institutional memory altered the recommendation based on prior human precedents and supplier conventions.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.caption("ℹ️ *Confidence is a deterministic heuristic reflecting sample size and past approver agreement, not a calibrated statistical probability.*")
