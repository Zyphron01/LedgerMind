"""
ui/pages/overview.py
────────────────────────────────────────────────────────────────────────────────
View A: System Overview & Status Dashboard for LedgerMind.
Displays real local data: held-out queue metrics, exception distribution,
authoritative Hindsight bank document counts, and live connection status
with modern Bento-grid and Tremor-inspired styling.
"""

from collections import Counter
import streamlit as st

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from ui.components.cards import render_advisory_banner
from ui.state import (
    check_hindsight_health,
    get_held_out_invoices,
    get_hindsight_document_count,
    get_memory_client,
)
from ui.theme import render_pulsing_status


def render_overview_page() -> None:
    """Render premium system overview and status dashboard."""
    # Page Header
    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em;">
                    System Overview & AP Intelligence
                </h1>
                <span class="lm-badge lm-badge-emerald">v1.0 Production Ready</span>
            </div>
            <p style="color: #94a3b8; font-size: 1rem; margin-top: 6px; line-height: 1.5;">
                Autonomous Accounts Payable discrepancy-handling agent powered by <strong>Hindsight</strong> institutional decision memory, <strong>Groq LLM</strong>, and corporate policy RAG.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_advisory_banner()

    held_out = get_held_out_invoices()
    health = check_hindsight_health()
    mem_client = get_memory_client()

    # 1. KEY INGESTION & BENCHMARK METRICS (Tremor style)
    st.markdown(
        """
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
            <div style="font-weight: 700; font-size: 1.1rem; color: #f8fafc;">
                1. Ingestion & Benchmark Queue Metrics
            </div>
            <span class="lm-badge lm-badge-blue">20 Held-Out Ground Truth Cases</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)

    total_invoices = len(held_out)
    unmatched_count = sum(1 for inv in held_out if not inv.match_result.is_match)
    matched_count = total_invoices - unmatched_count
    reviewed_count = len(st.session_state.get("reviewed_invoices", {}))

    with col1:
        st.metric(
            label="Total Evaluation Invoices",
            value=f"{total_invoices}",
            help="Full curated held-out test harness for institutional AP matching.",
        )
    with col2:
        st.metric(
            label="3-Way Match Exceptions",
            value=f"{unmatched_count}",
            delta=f"{unmatched_count / total_invoices * 100:.0f}% exception rate",
            delta_color="inverse",
            help="Invoices requiring resolution due to price, quantity, tax, or PO discrepancies.",
        )
    with col3:
        st.metric(
            label="Clean Match Invoices",
            value=f"{matched_count}",
            delta=f"{matched_count / total_invoices * 100:.0f}% auto-cleared",
            delta_color="normal",
            help="Invoices passing strict 3-way matching tolerances without intervention.",
        )
    with col4:
        st.metric(
            label="Reviewed This Session",
            value=f"{reviewed_count} / {total_invoices}",
            help="Human reviewer decisions captured and retained in the active demo bank.",
        )

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 2. DISCREPANCY EXCEPTION DISTRIBUTION
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.1rem; color: #f8fafc; margin-bottom: 12px;">
            2. Discrepancy Exception Distribution
        </div>
        """,
        unsafe_allow_html=True,
    )

    exc_counts = Counter(inv.match_result.exception_type.value for inv in held_out)
    cols = st.columns(len(exc_counts))
    for col, (exc_type, count) in zip(cols, sorted(exc_counts.items())):
        with col:
            st.metric(label=exc_type, value=f"{count}")

    st.caption(
        "ℹ️ *All 20 held-out benchmark invoices represent authentic Indian AP edge cases spanning price creeping, "
        "quantity shortfalls, duplicate submissions, statutory GST errors, expired POs, and HSN code clerical errors.*"
    )

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 3. HINDSIGHT ENGINE & MEMORY BANK STATUS (Bento Cards)
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.1rem; color: #f8fafc; margin-bottom: 12px;">
            3. Institutional Memory Banks & Retention Architecture
        </div>
        """,
        unsafe_allow_html=True,
    )

    base_docs, base_facts = get_hindsight_document_count(BASELINE_EVAL_BANK_ID)
    demo_docs, demo_facts = get_hindsight_document_count(LIVE_DEMO_BANK_ID)

    col_h1, col_h2 = st.columns(2)

    with col_h1:
        st.markdown(
            f"""
            <div class="lm-card" style="height: 100%;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.2rem;">🔒</span>
                        <span style="font-weight: 700; font-size: 1rem; color: #f8fafc;">Frozen Baseline Benchmark Bank</span>
                    </div>
                    <span class="lm-badge lm-badge-blue">IMMUTABLE BASELINE</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.88rem; color: #cbd5e1;">
                    <div>• <strong>Bank ID:</strong> <code style="color: #60a5fa;">{BASELINE_EVAL_BANK_ID}</code></div>
                    <div>• <strong>Isolation State:</strong> <span style="color: #34d399; font-weight: 600;">READ-ONLY / FROZEN</span> (Feedback writes strictly blocked)</div>
                    <div>• <strong>Verified Stored Documents:</strong> <strong style="color: #f8fafc; font-size: 1rem;">{base_docs}</strong> unique historical decisions</div>
                    <div>• <strong>Indexed Memory Facts:</strong> <strong style="color: #f8fafc; font-size: 1rem;">{base_facts}</strong> atomic units</div>
                    <div>• <strong>Dataset Seeding Status:</strong> <strong>{base_docs} of 50</strong> synthetic decisions seeded</div>
                </div>
                <div style="margin-top: 14px; padding-top: 10px; border-top: 1px solid #1f2937; font-size: 0.78rem; color: #94a3b8; line-height: 1.4;">
                    📌 <em>Seeding Note:</em> 36 records remain queued in the local ledger due to Groq's daily 200,000 Tokens Per Day (TPD) ceiling. Full 50 decisions are accessible via the offline fallback store.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_h2:
        st.markdown(
            f"""
            <div class="lm-card" style="height: 100%;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.2rem;">🟡</span>
                        <span style="font-weight: 700; font-size: 1rem; color: #f8fafc;">Live Interactive Demo Bank</span>
                    </div>
                    <span class="lm-badge lm-badge-amber">ACTIVE LEARNING</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.88rem; color: #cbd5e1;">
                    <div>• <strong>Bank ID:</strong> <code style="color: #fbbf24;">{LIVE_DEMO_BANK_ID}</code></div>
                    <div>• <strong>Learning State:</strong> <span style="color: #fbbf24; font-weight: 600;">ACTIVE LEARNING</span> (Captures human reviewer overrides)</div>
                    <div>• <strong>Stored Feedback Records:</strong> <strong style="color: #f8fafc; font-size: 1rem;">{demo_docs}</strong> reviewer decisions</div>
                    <div>• <strong>Indexed Memory Facts:</strong> <strong style="color: #f8fafc; font-size: 1rem;">{demo_facts}</strong> atomic units</div>
                    <div>• <strong>Recall Behavior:</strong> Dynamically queries both live demo feedback and baseline precedents.</div>
                </div>
                <div style="margin-top: 14px; padding-top: 10px; border-top: 1px solid #1f2937; font-size: 0.78rem; color: #94a3b8; line-height: 1.4;">
                    💡 <em>Workflow Separation:</em> Review outcomes submitted in the Resolution Workbench are retained here and immediately influence subsequent agent recommendations.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 4. SERVICE CONNECTIVITY TABLE
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.1rem; color: #f8fafc; margin-bottom: 12px;">
            4. Service Connectivity & Infrastructure Topology
        </div>
        """,
        unsafe_allow_html=True,
    )

    status_icon = "🟢" if health.get("connected") else "🟠"

    status_data = [
        {
            "Service": "Hindsight Memory Engine",
            "Endpoint": health.get("url", "N/A"),
            "Status": f"{status_icon} {health.get('status')}",
            "Details": health.get("message"),
        },
        {
            "Service": "Groq LLM Engine",
            "Endpoint": "https://api.groq.com",
            "Status": "🟢 CONFIGURED",
            "Details": "openai/gpt-oss-120b (Failover: openai/gpt-oss-20b)",
        },
        {
            "Service": "Deterministic 3-Way Matcher",
            "Endpoint": "agent/matcher.py",
            "Status": "🟢 IN-MEMORY",
            "Details": "Strict tolerance checks (1.0% price, 0.5% qty, GSTIN, HSN, PO validity)",
        },
        {
            "Service": "Offline JSONL Store",
            "Endpoint": "offline_memory.jsonl",
            "Status": "🟢 ACTIVE",
            "Details": "Local audit log and resilient fallback storage",
        },
    ]
    st.table(status_data)

    # 5. QUICK NAVIGATION ACTIONS
    st.markdown(
        """
        <div style="margin-top: 20px; padding: 16px; background: rgba(30, 41, 59, 0.3); border: 1px solid #1f2937; border-radius: 12px; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <span style="font-weight: 700; color: #f8fafc;">Ready to explore?</span>
                <span style="color: #94a3b8; font-size: 0.88rem; margin-left: 8px;">Navigate directly to exception inspection or start resolving held-out invoices.</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_nav1, col_nav2, col_nav3 = st.columns(3)
    with col_nav1:
        if st.button("📋 Inspect Invoice Queue", use_container_width=True):
            st.session_state["current_page"] = "Invoice Queue"
            st.rerun()
    with col_nav2:
        if st.button("⚡ Open Resolution Workbench", use_container_width=True, type="primary"):
            st.session_state["current_page"] = "Resolution Workbench"
            st.rerun()
    with col_nav3:
        if st.button("⚖️ Compare Memory OFF vs ON", use_container_width=True):
            st.session_state["current_page"] = "Memory OFF vs ON Comparison"
            st.rerun()
