"""
ui/pages/queue.py
────────────────────────────────────────────────────────────────────────────────
View B: Invoice Queue & 3-Way Match Inspector for LedgerMind.
Displays all 20 held-out evaluation invoices with filtering, discrepancy summaries,
and comprehensive multi-document inspection (Invoice vs PO vs GRN vs Match).
Hidden expected resolution labels are strictly suppressed.
"""

from decimal import Decimal
import pandas as pd
import streamlit as st

from data.models import HeldOutInvoice
from ui.components.cards import render_advisory_banner, render_discrepancy_banner
from ui.state import get_held_out_invoices


def render_queue_page() -> None:
    """Render functional invoice queue and 3-way match inspector."""
    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em;">
                    AP Invoice Exception Queue
                </h1>
                <span class="lm-badge lm-badge-violet">3-Way Reconciliation</span>
            </div>
            <p style="color: #94a3b8; font-size: 1rem; margin-top: 6px; line-height: 1.5;">
                Inspect incoming supplier invoices against purchase orders and warehouse receipts. Filter by vendor, discrepancy type, or review status.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_advisory_banner()

    held_out = get_held_out_invoices()
    reviewed_map = st.session_state.get("reviewed_invoices", {})

    # 1. FILTERS CONTAINER
    with st.container():
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px 20px 8px 20px; margin-bottom: 18px;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                    <span>⚡</span> Filter Queue
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            vendor_filter = st.selectbox(
                "Filter by Vendor",
                ["All Vendors"] + sorted(list({inv.invoice.vendor_name for inv in held_out})),
            )
        with col_f2:
            exc_filter = st.selectbox(
                "Filter by Exception Type",
                ["All Exceptions"] + sorted(list({inv.match_result.exception_type.value for inv in held_out})),
            )
        with col_f3:
            status_filter = st.selectbox(
                "Filter by Review Status",
                ["All Statuses", "Pending Review", "Reviewed"],
            )

    # Filter invoices
    filtered: list[HeldOutInvoice] = []
    for item in held_out:
        inv_no = item.invoice.invoice_number
        is_reviewed = inv_no in reviewed_map

        if vendor_filter != "All Vendors" and item.invoice.vendor_name != vendor_filter:
            continue
        if exc_filter != "All Exceptions" and item.match_result.exception_type.value != exc_filter:
            continue
        if status_filter == "Pending Review" and is_reviewed:
            continue
        if status_filter == "Reviewed" and not is_reviewed:
            continue
        filtered.append(item)

    st.markdown(
        f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin: 12px 0 10px 0;">
            <div style="font-size: 0.9rem; color: #94a3b8;">
                Showing <strong style="color: #f8fafc;">{len(filtered)}</strong> of <strong style="color: #f8fafc;">{len(held_out)}</strong> invoices
            </div>
            <div style="display: flex; gap: 8px;">
                <span class="lm-badge lm-badge-amber">{sum(1 for i in filtered if i.invoice.invoice_number not in reviewed_map)} Pending</span>
                <span class="lm-badge lm-badge-emerald">{sum(1 for i in filtered if i.invoice.invoice_number in reviewed_map)} Reviewed</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2. QUEUE TABLE
    rows = []
    for item in filtered:
        inv = item.invoice
        match = item.match_result
        is_rev = inv.invoice_number in reviewed_map
        status_str = f"✅ {reviewed_map[inv.invoice_number]['decision']}" if is_rev else "⏳ Pending Review"

        rows.append({
            "Invoice No": inv.invoice_number,
            "Vendor": inv.vendor_name,
            "Amount (INR)": f"₹{inv.total_inr:,.2f}",
            "Exception Type": match.exception_type.value,
            "Discrepancy Summary": match.explanation[:65] + ("..." if len(match.explanation) > 65 else ""),
            "Review Status": status_str,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("<div style='margin-bottom: 24px;'></div>", unsafe_allow_html=True)

    # 3. INVOICE SELECTOR & INSPECTOR
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
            <span style="font-size: 1.3rem;">🔍</span>
            <span style="font-weight: 700; font-size: 1.25rem; color: #f8fafc;">Three-Way Match Deep Inspector</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    current_selected = st.session_state.get("selected_invoice_id", held_out[0].invoice.invoice_number)
    available_ids = [inv.invoice.invoice_number for inv in held_out]
    default_idx = available_ids.index(current_selected) if current_selected in available_ids else 0

    col_pick, col_cta = st.columns([3, 1])
    with col_pick:
        selected_id = st.selectbox(
            "Select Invoice to Inspect:",
            available_ids,
            index=default_idx,
            format_func=lambda x: f"{x} — {next(i.invoice.vendor_name for i in held_out if i.invoice.invoice_number == x)} ({next(i.match_result.exception_type.value for i in held_out if i.invoice.invoice_number == x)})",
        )
        st.session_state["selected_invoice_id"] = selected_id

    # Retrieve selected invoice object
    selected_item = next(i for i in held_out if i.invoice.invoice_number == selected_id)
    inv = selected_item.invoice
    po = selected_item.po
    grn = selected_item.grn
    match = selected_item.match_result

    with col_cta:
        st.write("")
        st.write("")
        if st.button("🚀 Resolve in Workbench", type="primary", use_container_width=True):
            st.session_state["current_page"] = "Resolution Workbench"
            st.rerun()

    # Discrepancy Banner
    render_discrepancy_banner(match)

    # Tabs for Multi-Document Reconciliation Inspection
    tab_match, tab_inv, tab_po, tab_grn = st.tabs([
        "⚡ Deterministic Match Findings",
        "📄 Supplier Invoice",
        "📑 Purchase Order (PO)",
        "📦 Goods Receipt Note (GRN)",
    ])

    with tab_match:
        st.markdown(f"#### Match Summary: `{match.exception_type.value}`")
        st.write(f"**Primary Finding:** {match.explanation}")

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric("Invoice Total", f"₹{match.invoice_amount_inr:,.2f}")
        with col_m2:
            st.metric("Expected PO Total", f"₹{match.expected_amount_inr:,.2f}")
        with col_m3:
            st.metric(
                "Financial Variance",
                f"₹{abs(match.variance_inr):,.2f}",
                delta=f"{'+' if match.variance_inr > 0 else ''}₹{match.variance_inr:,.2f}",
                delta_color="inverse" if match.variance_inr != Decimal("0.00") else "off",
            )

        if match.discrepancies:
            st.markdown("##### Detailed Discrepancy Findings:")
            for d in match.discrepancies:
                st.warning(f"**[{d.field}]:** {d.message} (Invoice: `{d.invoice_value}` vs Expected: `{d.expected_value}`)")
        else:
            st.success("No line item discrepancies detected.")

    with tab_inv:
        st.markdown(f"#### Invoice: `{inv.invoice_number}`")
        col_i1, col_i2, col_i3 = st.columns(3)
        with col_i1:
            st.write(f"• **Vendor:** {inv.vendor_name}")
            st.write(f"• **GSTIN:** `{inv.gstin}`")
        with col_i2:
            st.write(f"• **Invoice Date:** {inv.invoice_date}")
            st.write(f"• **Referenced PO:** `{inv.po_number}`")
            if inv.grn_number:
                st.write(f"• **Linked GRN:** `{inv.grn_number}`")
        with col_i3:
            st.write(f"• **Subtotal (Excl Tax):** ₹{inv.total_excl_tax_inr:,.2f}")
            st.write(f"• **GST Amount:** ₹{inv.gst_amount_inr:,.2f}")
            st.write(f"• **Total Invoice Amount:** **₹{inv.total_inr:,.2f}**")

        st.markdown("##### Billed Line Item Specifications:")
        inv_lines = [{
            "Item Description": inv.item_description,
            "HSN Code": inv.hsn_code,
            "Quantity": f"{inv.quantity}",
            "Unit Price (INR)": f"₹{inv.unit_price_inr:,.2f}",
            "GST Rate": f"{inv.gst_rate * 100:.0f}%",
            "Subtotal (Excl Tax)": f"₹{inv.total_excl_tax_inr:,.2f}",
            "Total (INR)": f"₹{inv.total_inr:,.2f}",
        }]
        st.dataframe(pd.DataFrame(inv_lines), use_container_width=True, hide_index=True)

    with tab_po:
        st.markdown(f"#### Purchase Order: `{po.po_number}`")
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            st.write(f"• **Vendor:** {po.vendor_name}")
            st.write(f"• **GSTIN:** `{po.gstin}`")
        with col_p2:
            st.write(f"• **Issue Date:** {po.issue_date}")
            st.write(f"• **Valid Until:** {po.valid_until}")
        with col_p3:
            st.write(f"• **Subtotal (Excl Tax):** ₹{po.total_excl_tax_inr:,.2f}")
            st.write(f"• **GST Amount:** ₹{po.gst_amount_inr:,.2f}")
            st.write(f"• **PO Contracted Total:** **₹{po.total_inr:,.2f}**")

        st.markdown("##### Contracted PO Line Item Specifications:")
        po_lines = [{
            "Item Description": po.item_description,
            "HSN Code": po.hsn_code,
            "Contracted Qty": f"{po.quantity}",
            "Contracted Unit Price": f"₹{po.unit_price_inr:,.2f}",
            "GST Rate": f"{po.gst_rate * 100:.0f}%",
            "Total (INR)": f"₹{po.total_inr:,.2f}",
        }]
        st.dataframe(pd.DataFrame(po_lines), use_container_width=True, hide_index=True)

    with tab_grn:
        if grn:
            st.markdown(f"#### Goods Receipt Note: `{grn.grn_number}`")
            col_g1, col_g2, col_g3 = st.columns(3)
            with col_g1:
                st.write(f"• **GRN Number:** `{grn.grn_number}`")
                st.write(f"• **Linked PO:** `{grn.po_number}`")
            with col_g2:
                st.write(f"• **Receipt Date:** {grn.receipt_date}")
                st.write(f"• **Delivered Units:** {grn.received_quantity}")
            with col_g3:
                st.write(f"• **Accepted Units:** {grn.accepted_quantity}")
                st.write(f"• **Rejected Units:** {grn.rejected_quantity}")

            st.write(f"• **Inspection QA Notes:** {grn.inspection_notes}")

            grn_lines = [{
                "GRN Number": grn.grn_number,
                "Receipt Date": grn.receipt_date,
                "Delivered Qty": f"{grn.received_quantity}",
                "Accepted Qty": f"{grn.accepted_quantity}",
                "Rejected Qty": f"{grn.rejected_quantity}",
                "Inspection Notes": grn.inspection_notes,
            }]
            st.dataframe(pd.DataFrame(grn_lines), use_container_width=True, hide_index=True)
        else:
            st.info("ℹ️ No Goods Receipt Note (GRN) on record. (Applicable for service contracts or unreceived goods).")
