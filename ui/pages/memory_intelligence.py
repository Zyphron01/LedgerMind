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
from agent.confidence import extract_decision_from_memory
from agent.resolver import normalize_and_deduplicate_memories
from data.models import ApproverDecision, Vendor
from data.store import list_all_vendor_names, list_vendors
from data.vendors import ALL_VENDORS, VENDORS_BY_SLUG, get_vendor_slug
from memory.operations import get_vendor_profile, recall_vendor_history
from memory.reflect_cache import ReflectCache
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

    canonical_slug = get_vendor_slug(selected_name)
    raw_slug = selected_name.lower().replace(" ", "-").replace(".", "")

    synth_vendor = next((v for v in ALL_VENDORS if v.name == selected_name), None)
    if synth_vendor:
        selected_vendor = synth_vendor
    else:
        all_v_dicts = {v["name"]: v for v in list_vendors()}
        v_info = all_v_dicts.get(selected_name, {})
        v_gstin = v_info.get("gstin", "27AABCA0000A1Z0")
        v_cat = v_info.get("category", "General Procurement")
        v_slug = v_info.get("slug", canonical_slug)
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
    slug = canonical_slug

    slug_pill_html = f'<code style="color: #60a5fa; background: rgba(59, 130, 246, 0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.82rem;">{slug}</code>'
    if raw_slug != slug:
        slug_pill_html += f' <code style="color: #94a3b8; background: rgba(148, 163, 184, 0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.78rem;" title="Database alias slug">alias: {raw_slug}</code>'

    # VENDOR INFO CARD (Bento Style)
    st.markdown(
        f"""
        <div class="lm-card" style="margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.3rem;">🏢</span>
                    <span style="font-weight: 800; font-size: 1.15rem; color: #f8fafc;">{selected_vendor.name}</span>
                    {slug_pill_html}
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

    # Retrieve vendor memories with multi-slug resilience
    with st.spinner("Retrieving historical records from memory..."):
        recalled = recall_vendor_history(
            client=mem_client,
            bank_id=chosen_bank,
            vendor_name=selected_name,
            vendor_slug=selected_vendor.slug,
            limit=15,
        )

    # Determine provenance and fallback reasons
    is_offline = (
        mem_client.last_recall_source == "offline"
        or (recalled and any(m.is_offline_fallback for m in recalled))
    )
    fallback_reason = mem_client.last_fallback_reason

    if not recalled:
        if chosen_bank == BASELINE_EVAL_BANK_ID and not synth_vendor:
            st.info(
                f"ℹ️ **No baseline benchmark records**: Vendor `{selected_name}` is a live-demo / user-created supplier. "
                f"Historical review records are stored in **🟡 Live Demo Bank ({LIVE_DEMO_BANK_ID})**."
            )
        else:
            if fallback_reason:
                st.warning(f"⚠️ Hindsight retrieval notice ({fallback_reason}). Local offline store contains 0 records for `{selected_name}` in bank `{chosen_bank}`.")
            else:
                st.info(f"No precedent review records currently recorded in bank `{chosen_bank}` for vendor `{selected_name}`.")
    else:
        prov_label = "🟠 OFFLINE AUDIT STORE (Deterministic Local Fallback)" if is_offline else "🟢 LIVE HINDSIGHT ENGINE (Active Container)"
        st.markdown(
            f"""
            <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                <span>Provenance:</span>
                <strong style="color: {'#fb923c' if is_offline else '#4ade80'};">{prov_label}</strong>
                <span>• Bank: <code>{chosen_bank}</code></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Source-level grouping: collapse extracted fact fragments under originating decisions
        grouped_memories = normalize_and_deduplicate_memories(recalled, max_items=len(recalled))
        verified_decisions = [
            m for m in grouped_memories
            if not getattr(m, "is_ungrouped", False) and not (m.document_id or "").startswith("fact-")
        ]
        ungrouped_facts = [
            m for m in grouped_memories
            if getattr(m, "is_ungrouped", False) or (m.document_id or "").startswith("fact-")
        ]

        decisions_list = []
        for m in verified_decisions:
            dec = extract_decision_from_memory(m)
            if dec:
                decisions_list.append(dec.value)
            else:
                for t in m.tags:
                    if t.startswith("decision:"):
                        decisions_list.append(t.split(":", 1)[1].upper())
                        break

        # Display distinct metrics for raw records and verified source decisions
        col_m1, col_m2, col_m3 = st.columns([1, 1, 2])
        with col_m1:
            st.metric("Raw Memory Records", f"{len(recalled)}")
        with col_m2:
            st.metric("Unique Source Decisions", f"{len(verified_decisions)}")
        with col_m3:
            if decisions_list:
                counts = Counter(decisions_list)
                summary_str = " • ".join([f"{k}: {v}" for k, v in counts.items()])
                st.metric("Historical Decision Pattern", summary_str)
            else:
                st.metric("Historical Decision Pattern", "No verified decisions" if not verified_decisions else "Pending categorization")

        if ungrouped_facts:
            st.caption(
                f"ℹ️ {len(recalled)} raw record(s) consolidated into {len(verified_decisions)} verified precedent review(s) "
                f"and {len(ungrouped_facts)} unattributed observation(s)."
            )

        st.markdown(
            f"""
            <div style="font-weight: 700; font-size: 1rem; color: #f8fafc; margin: 16px 0 10px 0;">
                Verified Precedent Reviews ({len(verified_decisions)}):
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not verified_decisions:
            st.info("No verified historical decision reviews identified for this supplier.")

        for idx, m in enumerate(verified_decisions, 1):
            doc = m.document_id or m.id[:12]
            source_badge = "Offline Fallback" if m.is_offline_fallback else "Hindsight Online"
            dec = extract_decision_from_memory(m)
            dec_badge = f" • Decision: {dec.value}" if dec else ""
            fact_count = len(getattr(m, "supporting_facts", []))
            facts_badge = f" • {fact_count} extracted fact{'s' if fact_count != 1 else ''}" if fact_count > 0 else ""

            with st.expander(f"[{idx}] Precedent: {doc} ({source_badge}{dec_badge}{facts_badge})", expanded=(idx <= 2)):
                st.markdown("**Primary Decision Review:**")
                st.write(m.text)
                if m.supporting_facts:
                    st.markdown("**Extracted Memory Facts & Observations:**")
                    for f in m.supporting_facts:
                        st.markdown(f"- {f}")
                if m.metadata:
                    clean_meta = {k: v for k, v in m.metadata.items() if k not in ("text", "content")}
                    if clean_meta:
                        st.caption(
                            "Metadata: " + " • ".join([f"**{k}**: `{v}`" for k, v in clean_meta.items()])
                        )
                if m.tags:
                    st.caption("Tags: " + " • ".join([f"`{t}`" for t in m.tags]))
                st.caption(f"Citation: `{m.to_citation_summary()}`")

        if ungrouped_facts:
            with st.expander(f"Unattributed Memory Facts ({len(ungrouped_facts)})", expanded=False):
                st.caption("These individual memory observations lack a verified source document ID and could not be linked to a known review.")
                for u_idx, u in enumerate(ungrouped_facts, 1):
                    st.markdown(f"- **Fact [{u_idx}]:** {u.text}")
                    if u.tags:
                        st.caption("  Tags: " + " • ".join([f"`{t}`" for t in u.tags]))

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
        refresh_btn = st.button("🔄 Generate / Refresh Profile", help="Triggers a fresh Hindsight reflect() operation and updates disk cache.")

    try:
        # Check cache first to avoid automatic model invocations on page navigation / dropdown changes
        cached_prof = mem_client.reflect_cache.get(canonical_slug, bank_id=chosen_bank)
        reflect_prof = None

        if refresh_btn:
            with st.spinner("Synthesizing longitudinal vendor profile with Hindsight reflect()..."):
                reflect_prof = get_vendor_profile(
                    client=mem_client,
                    bank_id=chosen_bank,
                    vendor_slug=canonical_slug,
                    vendor_name=selected_name,
                    force_refresh=True,
                )
        elif cached_prof and not getattr(cached_prof, "is_error", False) and not mem_client.reflect_cache.is_failed_summary(getattr(cached_prof, "summary", "")):
            reflect_prof = cached_prof

        is_err = (
            getattr(reflect_prof, "is_error", False)
            or (reflect_prof and ReflectCache.is_failed_summary(getattr(reflect_prof, "summary", "")))
        )
        summary_val = getattr(reflect_prof, "summary", "") if reflect_prof else ""

        if reflect_prof and not is_err and summary_val:
            is_cached = getattr(reflect_prof, "cached", False)
            gen_at = getattr(reflect_prof, "generated_at", None)
            gen_str = gen_at.strftime('%Y-%m-%d %H:%M:%S UTC') if gen_at else "Just now"
            st.markdown(
                f"""
                <div class="lm-callout lm-callout-policy" style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-weight: 700; color: #f8fafc; font-size: 0.95rem;">Synthesized Vendor Longitudinal Profile</span>
                        <span class="lm-badge lm-badge-violet">{'Disk Cached' if is_cached else 'Fresh Synthesis'}</span>
                    </div>
                    <div style="color: #e2e8f0; font-size: 0.92rem; line-height: 1.6;">
                        {summary_val}
                    </div>
                    <div style="margin-top: 8px; font-size: 0.78rem; color: #94a3b8;">
                        Bank: <code>{chosen_bank}</code> • Generated at: {gen_str}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif reflect_prof and is_err:
            err_msg = getattr(reflect_prof, "error_message", None) or summary_val
            st.info(
                f"ℹ️ **Hindsight Reflect Synthesis Notice**: Longitudinal synthesis is unavailable ({err_msg or 'LLM inference provider not configured'}). "
                f"Direct decision precedents and reviewer rationale are recalled above."
            )
        else:
            st.info(
                f"ℹ️ **No Synthesized Profile Cached**: A longitudinal reflection for `{selected_name}` in bank `{chosen_bank}` is not currently cached on disk. "
                "Click **'🔄 Generate / Refresh Profile'** above to perform synthesis, or review direct decision precedents above."
            )
    except Exception as e:
        st.info(f"ℹ️ Reflect synthesis notice: {e}. Direct historical recall remains fully operational.")

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
    summary = budget.get_usage_summary()

    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    with col_b1:
        st.metric("Cloud Retain Tokens", f"{budget.cloud_retain_tokens:,} / {budget.max_retain_tokens:,}")
    with col_b2:
        st.metric("Cloud Reflect Calls", f"{budget.cloud_reflect_calls} / {budget.max_reflect_calls}")
    with col_b3:
        st.metric("Remaining Cloud Budget", f"{summary['remaining_reflect_calls']} calls")
    with col_b4:
        st.metric("Local Calls Logged", f"{budget.local_reflect_calls} calls")

    st.caption(
        f"🛡️ **Budget Guard & Audit Telemetry**: Cloud caps apply strictly to chargeable Hindsight Cloud operations ({budget.cloud_reflect_calls} used). "
        f"Local operations ({budget.local_reflect_calls} reflect calls logged) run via the local container for observability without consuming cloud API quotas."
    )
