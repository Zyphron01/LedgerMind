"""
ui/pages/workbench.py
────────────────────────────────────────────────────────────────────────────────
View C: Resolution Workbench & Human-in-the-Loop Review for LedgerMind.
Allows interactive execution of the resolution agent with Memory ON or OFF,
displays evidence citations, calculates heuristic confidence, and retains
human review outcomes into the live demonstration memory bank.
"""

from decimal import Decimal
import uuid
import streamlit as st

from agent.feedback import FeedbackSubmission, process_human_feedback
from agent.resolver import ResolutionAgent, ResolutionProposal
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, ApproverRole, HeldOutInvoice
from ui.components.cards import (
    render_advisory_banner,
    render_confidence_card,
    render_decision_badge,
    render_discrepancy_banner,
    render_evidence_memories,
    render_policy_intelligence_card,
)
from ui.state import (
    get_held_out_by_id,
    get_held_out_invoices,
    get_memory_client,
    get_resolution_agent,
)


def render_workbench_page() -> None:
    """Render functional AP exception resolution workbench with step-by-step layout."""
    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em;">
                    AP Exception Resolution Workbench
                </h1>
                <span class="lm-badge lm-badge-emerald">Human-in-the-Loop</span>
            </div>
            <p style="color: #94a3b8; font-size: 1rem; margin-top: 6px; line-height: 1.5;">
                Reconcile discrepancies, verify corporate policy directives, recall historical Hindsight precedents, and retain authorized human reviews.
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
                    <span>⚙️</span> Resolution Configuration
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_sel, col_mode = st.columns([2, 1])
        with col_sel:
            selected_id = st.selectbox(
                "Select Invoice for Resolution:",
                available_ids,
                index=available_ids.index(current_selected),
                format_func=lambda x: f"{x} — {next(i.invoice.vendor_name for i in held_out if i.invoice.invoice_number == x)}",
            )
            st.session_state["selected_invoice_id"] = selected_id

        with col_mode:
            memory_mode_choice = st.radio(
                "Agent Memory Mode:",
                ["Memory ON (Precedent-Grounded)", "Memory OFF (Zero-Context Baseline)"],
                index=0,
                horizontal=False,
            )
            memory_enabled = (memory_mode_choice == "Memory ON (Precedent-Grounded)")

        # Target bank selection
        col_bank1, col_bank2 = st.columns(2)
        with col_bank1:
            target_bank = st.selectbox(
                "Active Target Memory Bank:",
                [LIVE_DEMO_BANK_ID, BASELINE_EVAL_BANK_ID],
                index=0,
                format_func=lambda b: f"🟡 {b} (Interactive Learning)" if b == LIVE_DEMO_BANK_ID else f"🔒 {b} (Frozen Baseline [Read-Only])",
                help="The live demo bank queries both recent feedback and baseline precedents. Writes to the frozen baseline bank are blocked.",
            )
        with col_bank2:
            st.caption(
                "💡 **Workflow Separation:** In `ledgermind-live-demo`, the agent retrieves both authorized historical "
                "records and newly retained human feedback. The baseline benchmark bank remains immutable."
            )

    # Retrieve selected invoice
    target_held_out: HeldOutInvoice = get_held_out_by_id(selected_id)
    inv = target_held_out.invoice
    po = target_held_out.po
    grn = target_held_out.grn
    match_res = target_held_out.match_result

    # Discrepancy Banner
    render_discrepancy_banner(match_res)

    # RESOLUTION RUN TRIGGER
    cache_key = f"{selected_id}_{'on' if memory_enabled else 'off'}_{target_bank}"
    cached_proposals = st.session_state.setdefault("proposal_cache", {})

    col_run, col_status = st.columns([1, 2])
    with col_run:
        run_clicked = st.button("🤖 Generate Agent Proposal", type="primary", use_container_width=True)

    agent = get_resolution_agent()

    if run_clicked:
        with st.spinner("Querying institutional memory and synthesizing resolution proposal..."):
            try:
                proposal = agent.resolve(
                    invoice=inv,
                    po=po,
                    grn=grn,
                    match_result=match_res,
                    memory_enabled=memory_enabled,
                    bank_id=target_bank,
                )
                cached_proposals[cache_key] = proposal
            except Exception as e:
                st.error(f"Resolution generation failed: {e}")

    active_proposal: ResolutionProposal = cached_proposals.get(cache_key)

    if not active_proposal:
        st.info("👆 Click **'Generate Agent Proposal'** to run the resolution agent on this invoice.")
        return

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 1. DISPLAY AGENT RECOMMENDATION
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
            <span>1.</span> Agent Resolution Proposal
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_prop1, col_prop2, col_prop3 = st.columns(3)
    with col_prop1:
        st.markdown(
            f"""
            <div class="lm-card" style="padding: 18px 20px;">
                <div style="font-size: 0.8rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">
                    Proposed Action
                </div>
                <div>{render_decision_badge(active_proposal.proposed_action)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_prop2:
        st.metric(
            "Proposed Payable Amount",
            f"₹{active_proposal.proposed_amount_inr:,.2f}",
            delta=f"{'+' if active_proposal.proposed_amount_inr > inv.total_inr else ''}₹{active_proposal.proposed_amount_inr - inv.total_inr:,.2f} vs Billed",
            delta_color="inverse" if active_proposal.proposed_amount_inr != inv.total_inr else "off",
        )
    with col_prop3:
        token_info = active_proposal.token_usage.get("total_tokens", 0)
        mode_pill = '<span class="lm-badge lm-badge-emerald">MEMORY ON</span>' if active_proposal.memory_enabled else '<span class="lm-badge lm-badge-gray">MEMORY OFF</span>'
        st.markdown(
            f"""
            <div class="lm-card" style="padding: 18px 20px;">
                <div style="font-size: 0.8rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">
                    Inference Telemetry
                </div>
                <div style="font-size: 0.88rem; color: #cbd5e1;">
                    Tokens: <strong style="color: #f8fafc;">{token_info}</strong> &nbsp;|&nbsp; {mode_pill}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="lm-card" style="margin-top: 10px; margin-bottom: 20px;">
            <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                <span>💡</span> Reconciliation Rationale & Institutional Justification:
            </div>
            <div style="color: #cbd5e1; font-size: 0.92rem; line-height: 1.6;">
                {active_proposal.reasoning}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2. POLICY INTELLIGENCE & CONFLICT DETECTION
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
            <span>2.</span> Policy Intelligence & Conflict Detection
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_policy_intelligence_card(active_proposal)

    # 3. EVIDENCE & CONFIDENCE
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
            <span>3.</span> Institutional Memory & Evidence Grounding
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_confidence_card(active_proposal.confidence)

    if active_proposal.memory_enabled:
        render_evidence_memories(active_proposal.recalled_memories)
    else:
        st.info("ℹ️ Memory is currently **OFF**. The agent generated this recommendation without historical precedent context.")

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 4. HUMAN REVIEW & FEEDBACK RETENTION PANEL
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
            <span>4.</span> Authorized Human Reviewer Action & Institutional Learning
        </div>
        <p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 16px;">
            As an authorized AP Reviewer, submit your final decision. Your decision, rationale, and adjusted payable amount
            will be retained into persistent Hindsight memory to reinforce institutional knowledge for future runs.
        </p>
        """,
        unsafe_allow_html=True,
    )

    # Check if already reviewed in session
    reviewed_map = st.session_state.get("reviewed_invoices", {})
    already_reviewed = inv.invoice_number in reviewed_map

    if already_reviewed:
        rev_info = reviewed_map[inv.invoice_number]
        st.success(
            f"✅ **Invoice Reviewed in this Session:** {rev_info['decision']} by {rev_info['role']} "
            f"at ₹{rev_info['amount']:,.2f} on {rev_info['timestamp']}\n\n"
            f"• **Retained Document ID:** `{rev_info['document_id']}`\n\n"
            f"• **Rationale:** {rev_info['reason']}"
        )

    with st.form(key=f"human_review_form_{inv.invoice_number}"):
        col_act1, col_act2 = st.columns(2)
        with col_act1:
            decision_idx = ["APPROVED", "EDITED", "REJECTED", "ESCALATED"].index(active_proposal.proposed_action.value)
            human_decision_str = st.selectbox(
                "Reviewer Decision:",
                ["APPROVED", "EDITED", "REJECTED", "ESCALATED"],
                index=decision_idx,
                help="Approve the invoice, edit the payable amount, reject the claim, or escalate for vendor dispute.",
            )
            human_decision = ApproverDecision(human_decision_str)

        with col_act2:
            default_amount = float(active_proposal.proposed_amount_inr)
            if human_decision == ApproverDecision.REJECTED:
                default_amount = 0.0
            final_amount_float = st.number_input(
                "Final Approved Payable Amount (INR):",
                min_value=0.0,
                value=default_amount,
                step=100.0,
                format="%.2f",
            )

        col_role, col_bank_target = st.columns(2)
        with col_role:
            approver_role_str = st.selectbox(
                "Approver Role:",
                [r.value for r in ApproverRole],
                index=0,
            )
            approver_role = ApproverRole(approver_role_str)

        with col_bank_target:
            st.text_input("Target Memory Bank for Retention:", value=LIVE_DEMO_BANK_ID, disabled=True)
            st.caption("🔒 Benchmark isolation enforced: feedback writes are automatically routed to the live demo bank.")

        human_explanation = st.text_area(
            "Reviewer Rationale & Audit Justification (Mandatory):",
            placeholder="Document contractual, empirical, or business reason for this decision...",
            help="A detailed explanation is required for institutional memory retention and internal compliance.",
        )

        submit_review = st.form_submit_button("💾 Retain Decision & Record Outcome", type="primary", use_container_width=True)

    if submit_review:
        if not human_explanation.strip():
            st.error("Submission rejected: A detailed audit explanation is mandatory for institutional retention.")
            return

        final_amount_dec = Decimal(str(round(final_amount_float, 2)))

        # Create submission
        submission = FeedbackSubmission(
            invoice_number=inv.invoice_number,
            vendor_name=inv.vendor_name,
            exception_type=match_res.exception_type.value,
            agent_proposal=f"{active_proposal.proposed_action.value} at ₹{active_proposal.proposed_amount_inr:,.2f}",
            human_decision=human_decision,
            approver_role=approver_role,
            human_explanation=human_explanation.strip(),
            final_amount_inr=final_amount_dec,
            cited_memory_ids=active_proposal.cited_memory_ids,
        )

        # Retain via process_human_feedback
        mem_client = get_memory_client()
        with st.spinner("Retaining reviewer outcome into persistent Hindsight memory..."):
            try:
                feedback_res = process_human_feedback(
                    submission=submission,
                    memory_client=mem_client,
                    bank_id=LIVE_DEMO_BANK_ID,
                )

                # Record in session state
                reviewed_map[inv.invoice_number] = {
                    "decision": human_decision.value,
                    "role": approver_role.value,
                    "amount": final_amount_dec,
                    "reason": human_explanation.strip(),
                    "timestamp": feedback_res.retained_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "document_id": feedback_res.document_id,
                    "bank_id": LIVE_DEMO_BANK_ID,
                }
                st.session_state["reviewed_invoices"] = reviewed_map

                st.success(
                    f"🎉 **Outcome Successfully Retained into Persistent Memory!**\n\n"
                    f"• **Document ID:** `{feedback_res.document_id}`\n\n"
                    f"• **Bank ID:** `{LIVE_DEMO_BANK_ID}`\n\n"
                    f"• **Status:** `{feedback_res.status}`\n\n"
                    f"• **Timestamp:** {feedback_res.retained_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                    f"This decision is now indexed and will be recalled as precedent in subsequent resolutions."
                )

            except Exception as e:
                st.error(f"Failed to retain feedback to memory: {e}")
