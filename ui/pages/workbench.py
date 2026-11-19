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
                format_func=lambda x: f"{x} — {next(i.invoice.vendor_name for i in held_out if i.invoice.invoice_number == x)} [{'USER' if getattr(next(i for i in held_out if i.invoice.invoice_number == x), 'is_user_created', False) else 'SAMPLE'}]",
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
        if po is None:
            st.error("Cannot generate proposal: Referenced Purchase Order is missing from repository. Please link or create the PO first.")
            return

        # Invalidate existing cache entry to guarantee fresh live execution
        cached_proposals.pop(cache_key, None)

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
        fallback_pill = ' <span class="lm-badge lm-badge-amber" title="Synthesized via deterministic rule engine due to offline/unavailable LLM">FALLBACK</span>' if getattr(active_proposal, "llm_fallback", False) else ''
        st.markdown(
            f"""
            <div class="lm-card" style="padding: 18px 20px;">
                <div style="font-size: 0.8rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;">
                    Inference Telemetry
                </div>
                <div style="font-size: 0.88rem; color: #cbd5e1;">
                    Tokens: <strong style="color: #f8fafc;">{token_info}</strong> &nbsp;|&nbsp; {mode_pill}{fallback_pill}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if getattr(active_proposal, "llm_fallback", False):
        st.info("⚡ **Deterministic Fallback Active:** Groq inference was unavailable or offline. This resolution proposal was synthesized deterministically using LedgerMind's 3-way match rules and corporate policy constraints.")

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

    if getattr(active_proposal, "prior_audit_reviews", None):
        audit_doc_id = active_proposal.prior_audit_reviews[0].document_id
        st.markdown(
            f"""
            <div style="background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.35); border-left: 4px solid #f59e0b; border-radius: 6px; padding: 12px 16px; margin: 12px 0 16px 0;">
                <div style="font-weight: 700; color: #fbbf24; font-size: 0.9rem; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                    <span>📋</span> Prior Review on Record (Preserved for Audit Trail)
                </div>
                <div style="font-size: 0.85rem; color: #cbd5e1; line-height: 1.5;">
                    A historical human review submission (<code>{audit_doc_id}</code>) was found for this specific invoice.
                    To maintain strict evaluation integrity and prevent circular confidence inflation, this record is preserved for audit verification but <strong>strictly excluded from independent historical precedent scoring</strong>.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if active_proposal.memory_enabled:
        if active_proposal.recalled_memories and all(m.is_offline_fallback for m in active_proposal.recalled_memories):
            st.warning(
                "⚠️ **Data Lineage Notice:** Precedents below were retrieved from the **Local Offline JSONL Fallback Store** "
                "(Hindsight vector service timed out, was unreachable, or ran in offline mode). Records are preserved with honest offline provenance."
            )

        render_evidence_memories(
            active_proposal.recalled_memories,
            target_vendor_name=active_proposal.vendor_name,
        )
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

    # Check if already reviewed in database or session
    from data.store import get_review_history
    reviewed_map = st.session_state.get("reviewed_invoices", {})
    already_reviewed = inv.invoice_number in reviewed_map
    review_history = get_review_history(inv.invoice_number)

    if already_reviewed:
        rev_info = reviewed_map[inv.invoice_number]
        hstat = rev_info.get('hindsight_status', 'UNKNOWN')
        status_badge = "🟢 SYNCED" if hstat == "SYNCED" else ("🟡 PENDING SYNC" if hstat == "PENDING_SYNC" else f"⚪ {hstat}")
        st.markdown(
            f"""
            <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.35); border-left: 4px solid #10b981; border-radius: 6px; padding: 14px 16px; margin: 12px 0 16px 0;">
                <div style="font-weight: 700; color: #34d399; font-size: 0.95rem; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between;">
                    <span>📋 Active Review on Record: {rev_info['decision']}</span>
                    <span style="font-size: 0.8rem; padding: 2px 8px; border-radius: 4px; background: rgba(255,255,255,0.06);">{status_badge}</span>
                </div>
                <div style="font-size: 0.85rem; color: #cbd5e1; line-height: 1.5;">
                    <strong>Reviewer:</strong> {rev_info['role']} &bull; <strong>Payable Amount:</strong> ₹{rev_info['amount']:,.2f} &bull; <strong>Recorded:</strong> {rev_info['timestamp']}<br/>
                    <strong>Document ID:</strong> <code>{rev_info['document_id']}</code><br/>
                    <strong>Audit Rationale:</strong> {rev_info['reason']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if review_history:
        with st.expander(f"📜 View Superseded Review Version History ({len(review_history)} previous version{'s' if len(review_history) > 1 else ''})"):
            for prev in review_history:
                st.markdown(
                    f"**Version {prev.get('version', 1)}** &bull; Decision: `{prev.get('decision')}` &bull; "
                    f"Amount: ₹{Decimal(str(prev.get('approved_amount_inr', '0.00'))):,.2f} &bull; "
                    f"Superseded At: {prev.get('superseded_at')}\n\n"
                    f"*Rationale:* {prev.get('rationale')}\n\n"
                    f"*Doc ID:* `{prev.get('hindsight_doc_id')}` | *Status:* `{prev.get('hindsight_status')}`"
                )
                st.divider()

    if already_reviewed:
        st.warning("⚠️ **Notice:** An active review exists for this invoice. Submitting this form will supersede the current review, increment the version, and archive previous decisions to the immutable audit log.")

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

        # Retain via process_human_feedback & SQLite persistence
        mem_client = get_memory_client()
        with st.spinner("Recording reviewer outcome into persistent ledger and Hindsight memory..."):
            try:
                # 1. Attempt Hindsight retention
                feedback_res = process_human_feedback(
                    submission=submission,
                    memory_client=mem_client,
                    bank_id=LIVE_DEMO_BANK_ID,
                )
                hstatus = getattr(feedback_res, "hindsight_status", getattr(mem_client, "last_retain_status", "SYNCED"))

                # 2. Persist in authoritative SQLite database
                from data.store import save_human_review
                save_human_review(
                    invoice_number=inv.invoice_number,
                    decision=human_decision.value,
                    approver_role=approver_role.value,
                    approved_amount_inr=final_amount_dec,
                    rationale=human_explanation.strip(),
                    hindsight_doc_id=feedback_res.document_id,
                    hindsight_bank_id=LIVE_DEMO_BANK_ID,
                    hindsight_status=hstatus,
                    reviewed_at=feedback_res.retained_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                )

                # 3. Invalidate proposal cache and comparison cache for this invoice
                p_cache = st.session_state.get("proposal_cache", {})
                keys_to_remove = [k for k in list(p_cache.keys()) if k.startswith(f"{inv.invoice_number}_")]
                for k in keys_to_remove:
                    p_cache.pop(k, None)
                st.session_state["proposal_cache"] = p_cache

                comp_cache = st.session_state.get("comparison_cache", {})
                comp_cache.pop(inv.invoice_number, None)
                st.session_state["comparison_cache"] = comp_cache

                # 4. Record in session state
                reviewed_map[inv.invoice_number] = {
                    "decision": human_decision.value,
                    "role": approver_role.value,
                    "amount": final_amount_dec,
                    "reason": human_explanation.strip(),
                    "timestamp": feedback_res.retained_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "document_id": feedback_res.document_id,
                    "bank_id": LIVE_DEMO_BANK_ID,
                    "hindsight_status": hstatus,
                }
                st.session_state["reviewed_invoices"] = reviewed_map

                if hstatus == "SYNCED":
                    st.success(
                        f"🎉 **Outcome Successfully Retained into Persistent Hindsight Memory & Local Ledger!**\n\n"
                        f"• **Document ID:** `{feedback_res.document_id}`\n\n"
                        f"• **Bank ID:** `{LIVE_DEMO_BANK_ID}`\n\n"
                        f"• **Memory Engine Status:** `SYNCED (Live Hindsight Cluster)`\n\n"
                        f"• **Database Ledger:** `SAVED (SQLite)`\n\n"
                        f"• **Timestamp:** {feedback_res.retained_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                        f"This decision is now permanently stored and will be recalled as precedent in subsequent resolutions."
                    )
                elif hstatus == "PENDING_SYNC":
                    st.info(
                        f"💾 **Decision Saved to Persistent Ledger (Pending Hindsight Sync)**\n\n"
                        f"• **Invoice:** `{inv.invoice_number}`\n\n"
                        f"• **Decision:** `{human_decision.value}` by `{approver_role.value}` at ₹{final_amount_dec:,.2f}\n\n"
                        f"• **Database Ledger:** `SAVED (SQLite)`\n\n"
                        f"• **Retention Status:** `PENDING_SYNC` (Hindsight service offline; saved in SQLite audit log for auto-sync)\n\n"
                        f"• **Offline Document ID:** `{feedback_res.document_id}`"
                    )
                else:
                    st.info(
                        f"💾 **Decision Saved to Persistent Ledger (Offline Mode)**\n\n"
                        f"• **Invoice:** `{inv.invoice_number}`\n\n"
                        f"• **Decision:** `{human_decision.value}` by `{approver_role.value}` at ₹{final_amount_dec:,.2f}\n\n"
                        f"• **Database Ledger:** `SAVED (SQLite)`\n\n"
                        f"• **Retention Status:** `{hstatus}`"
                    )

            except Exception as e:
                st.error(f"Failed to record reviewer decision: {e}")
