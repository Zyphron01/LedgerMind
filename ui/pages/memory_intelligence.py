"""
ui/pages/memory_intelligence.py
────────────────────────────────────────────────────────────────────────────────
View E (Task 2D): Memory Intelligence & Behavioral Audit for LedgerMind.
Displays vendor-specific memory profiles, approval/rejection distribution,
cached Hindsight reflect summaries, live demo feedback records, and
token budget guard telemetry with modern Bento and Aceternity-inspired styling.
"""

from collections import Counter
from decimal import Decimal
import json
import streamlit as st

from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import ApproverDecision, Vendor
from data.store import list_all_vendor_names, list_vendors
from data.vendors import ALL_VENDORS, VENDORS_BY_SLUG
from memory.operations import get_vendor_profile
from ui.components.cards import render_advisory_banner
from ui.state import (
    get_hindsight_document_count,
    get_memory_client,
)


def render_memory_intelligence_page() -> None:
    """Render memory intelligence and vendor behavioral audit page."""
    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em;">
                    Institutional Memory Intelligence & Audit
                </h1>
                <span class="lm-badge lm-badge-violet">Vendor Profiles</span>
            </div>
            <p style="color: #94a3b8; font-size: 1rem; margin-top: 6px; line-height: 1.5;">
                Inspect vendor-specific memory profiles, longitudinal decision patterns, cached Hindsight reflections, and memory bank telemetry.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_advisory_banner()

    mem_client = get_memory_client()

    # 1. VENDOR SELECTOR & DOSSIER
    db_vendor_names = list_all_vendor_names()
    vendor_names = db_vendor_names if db_vendor_names else [v.name for v in ALL_VENDORS]
    selected_name = st.selectbox("Select Supplier / Vendor:", vendor_names)

    synth_vendor = next((v for v in ALL_VENDORS if v.name == selected_name), None)
    if synth_vendor:
        selected_vendor = synth_vendor
    else:
        all_v_dicts = {v["name"]: v for v in list_vendors()}
        v_info = all_v_dicts.get(selected_name, {})
        v_gstin = v_info.get("gstin", "27AABCA0000A1Z0")
        v_cat = v_info.get("category", "General Procurement")
        v_slug = v_info.get("slug", selected_name.lower().replace(" ", "-").replace(".", ""))
        selected_vendor = Vendor(
            name=selected_name,
            slug=v_slug,
            gstin=v_gstin,
            city="Operating City",
            state="India",
            state_code=v_gstin[:2] if len(v_gstin) >= 2 else "27",
            category=v_cat,
            standard_hsn="General",
            standard_gst_rate=Decimal("0.18"),
            quirk_description="User-registered enterprise supplier.",
            dominant_action=ApproverDecision.APPROVED,
        )
    slug = selected_vendor.slug

    # VENDOR INFO CARD (Bento Style)
    st.markdown(
        f"""
        <div class="lm-card" style="margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.3rem;">🏢</span>
                    <span style="font-weight: 800; font-size: 1.15rem; color: #f8fafc;">{selected_vendor.name}</span>
                    <code style="color: #60a5fa; background: rgba(59, 130, 246, 0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.82rem;">{slug}</code>
                </div>
                <span class="lm-badge lm-badge-emerald">{selected_vendor.category}</span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; font-size: 0.88rem; color: #cbd5e1; margin-bottom: 14px;">
                <div>• <strong>GSTIN:</strong> <code style="color: #e2e8f0;">{selected_vendor.gstin}</code></div>
                <div>• <strong>Location:</strong> {selected_vendor.city}, {selected_vendor.state}</div>
                <div>• <strong>Standard HSN/SAC:</strong> <code>{selected_vendor.standard_hsn}</code></div>
                <div>• <strong>Statutory GST Rate:</strong> <strong>{selected_vendor.standard_gst_rate * 100:.0f}%</strong></div>
            </div>
            <div style="background: rgba(30, 41, 59, 0.4); border-left: 3px solid #3b82f6; border-radius: 0 6px 6px 0; padding: 10px 14px; font-size: 0.88rem; color: #93c5fd;">
                <strong>Documented Behavioral Quirk:</strong> {selected_vendor.quirk_description}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

    # 2. VENDOR MEMORY RETRIEVAL & DECISION PATTERNS
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
            <span>1.</span> Vendor Decision History & Precedent Breakdown
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_bank_choice, col_refresh = st.columns([2, 1])
    with col_bank_choice:
        chosen_bank = st.radio(
            "Inspect Bank:",
            [BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID],
            format_func=lambda b: f"🔒 Baseline Bank ({b})" if b == BASELINE_EVAL_BANK_ID else f"🟡 Live Demo Bank ({b})",
            horizontal=True,
        )

    # Retrieve vendor memories
    with st.spinner("Retrieving historical records from memory..."):
        recalled = mem_client.recall(
            bank_id=chosen_bank,
            query=f"Historical decisions and reviews for {selected_vendor.name} {slug}",
            tags=[f"vendor:{slug}"],
            limit=15,
        )

    if not recalled:
        st.warning(f"No records found in bank `{chosen_bank}` for vendor `{slug}`.")
    else:
        # Deduplicate and extract decisions
        decisions_list = []
        unique_docs_seen = set()

        for m in recalled:
            doc_id = m.document_id or m.id
            if doc_id not in unique_docs_seen:
                unique_docs_seen.add(doc_id)
                dec = m.metadata.get("decision")
                if not dec:
                    for t in m.tags:
                        if t.startswith("decision:"):
                            dec = t.split(":", 1)[1].upper()
                            break
                if dec:
                    decisions_list.append(dec)

        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.metric("Unique Historical Decisions in Memory", f"{len(unique_docs_seen)}")
        with col_m2:
            if decisions_list:
                counts = Counter(decisions_list)
                summary_str = " • ".join([f"{k}: {v}" for k, v in counts.items()])
                st.metric("Historical Decision Pattern", summary_str)
            else:
                st.metric("Historical Decision Pattern", "Pending categorization")

        st.markdown(
            f"""
            <div style="font-weight: 700; font-size: 1rem; color: #f8fafc; margin: 16px 0 10px 0;">
                Retrieved Precedent Records ({len(recalled)}):
            </div>
            """,
            unsafe_allow_html=True,
        )

        for idx, m in enumerate(recalled, 1):
            doc = m.document_id or m.id[:12]
            with st.expander(f"[{idx}] Record: {doc} (Score: {m.score or 'N/A'})", expanded=(idx <= 2)):
                st.write(m.text)
                if m.tags:
                    st.caption("Tags: " + " • ".join([f"`{t}`" for t in m.tags]))

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 3. CACHED HINDSIGHT REFLECT SUMMARY
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
            <span>2.</span> Hindsight Reflect Behavioral Synthesis
        </div>
        <p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 14px;">
            Hindsight's <code>reflect()</code> synthesizes longitudinal behavioral patterns across all historical interactions with this supplier. LedgerMind caches reflect summaries to conserve LLM quotas.
        </p>
        """,
        unsafe_allow_html=True,
    )

    with col_refresh:
        st.write("")
        st.write("")
        refresh_btn = st.button("🔄 Refresh Vendor Profile", help="Triggers a fresh Hindsight reflect() operation and updates disk cache.")

    try:
        reflect_prof = get_vendor_profile(
            client=mem_client,
            bank_id=chosen_bank,
            vendor_slug=slug,
            force_refresh=refresh_btn,
        )
        if reflect_prof and reflect_prof.summary:
            st.markdown(
                f"""
                <div class="lm-callout lm-callout-policy" style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: #f8fafc; font-size: 0.95rem;">Synthesized Vendor Longitudinal Profile</span>
                        <span class="lm-badge lm-badge-violet">{'Disk Cached' if reflect_prof.cached else 'Fresh Synthesis'}</span>
                    </div>
                    <div style="color: #e2e8f0; font-size: 0.92rem; line-height: 1.6;">
                        {reflect_prof.summary}
                    </div>
                    <div style="margin-top: 8px; font-size: 0.78rem; color: #94a3b8;">
                        Generated at: {reflect_prof.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.info("No reflect summary currently available for this supplier. Click 'Refresh Vendor Profile' to synthesize.")
    except Exception as e:
        st.caption(f"Reflect profile synthesis info: {e}")

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 4. TOKEN BUDGET & TELEMETRY
    st.markdown(
        """
        <div style="font-weight: 700; font-size: 1.15rem; color: #f8fafc; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
            <span>3.</span> Token Budget Guard Telemetry
        </div>
        """,
        unsafe_allow_html=True,
    )

    budget = mem_client.budget_guard

    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        st.metric("Retain Calls Recorded", f"{budget.cumulative_retain_calls}")
    with col_b2:
        st.metric("Reflect Calls (Cloud Mode)", f"{budget.cumulative_reflect_calls} / {budget.max_reflect_calls}")
    with col_b3:
        st.metric("Retained Tokens (Cloud Mode)", f"{budget.cumulative_retain_tokens:,} / {budget.max_retain_tokens:,}")

    st.caption("🛡️ *The Token Budget Guard tracks retain/reflect calls in cloud mode to prevent accidental credit exhaustion.*")
