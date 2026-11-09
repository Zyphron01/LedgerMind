"""
ui/pages/intake.py
────────────────────────────────────────────────────────────────────────────────
View: New Invoice / Import Documents.
Allows manual document entry (Vendor + PO + GRN + Invoice) or CSV batch import.
Saves documents permanently into SQLite and runs deterministic 3-way matching.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import io
import pandas as pd
import streamlit as st

from agent.matcher import match_invoice
from data.models import GoodsReceiptNote, Invoice, PurchaseOrder
from data.store import (
    get_goods_receipt,
    get_goods_receipt_by_po,
    get_purchase_order,
    init_db,
    list_goods_receipts,
    list_purchase_orders,
    list_vendors,
    save_goods_receipt,
    save_invoice,
    save_purchase_order,
    save_vendor,
)
from data.vendors import ALL_VENDORS
from ui.components.cards import render_advisory_banner


SAMPLE_INVOICE_CSV_TEMPLATE = """invoice_number,vendor_name,gstin,invoice_date,po_number,grn_number,item_description,hsn_code,unit_price_inr,quantity,gst_rate
INV-USR-2025-001,Prabhav Infosystems,27AABCP1234D1Z5,2025-10-15,PO-USR-2025-001,GRN-USR-2025-001,Server Motherboards Supermicro,8471,1080.00,10,0.18
INV-USR-2025-002,Kiran Steel & Fabricators,27AABCK5678E1Z4,2025-10-18,PO-USR-2025-002,,Structural Steel Beams ISMB 300,7216,4200.00,5,0.18
"""

SAMPLE_PO_CSV_TEMPLATE = """po_number,vendor_name,gstin,issue_date,valid_until,item_description,hsn_code,unit_price_inr,quantity,gst_rate
PO-USR-2025-001,Prabhav Infosystems,27AABCP1234D1Z5,2025-09-01,2025-11-30,Server Motherboards Supermicro,8471,1000.00,10,0.18
PO-USR-2025-002,Kiran Steel & Fabricators,27AABCK5678E1Z4,2025-09-10,2025-12-10,Structural Steel Beams ISMB 300,7216,4200.00,5,0.18
"""


def render_intake_page() -> None:
    """Render the document intake, manual entry, and CSV import view."""
    init_db()

    st.markdown(
        """
        <div style="margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em;">
                    New Invoice & Document Intake
                </h1>
                <span class="lm-badge lm-badge-emerald">Persistent Ledger</span>
            </div>
            <p style="color: #94a3b8; font-size: 1rem; margin-top: 6px; line-height: 1.5;">
                Create or import new supplier invoices, associate them with purchase orders and goods receipt notes, and trigger deterministic 3-way reconciliation.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_advisory_banner()

    tab_manual, tab_csv, tab_templates = st.tabs(
        [
            "📝 Manual Document Entry",
            "📂 CSV Batch Import",
            "📋 Downloadable Templates",
        ]
    )

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 1: MANUAL DOCUMENT ENTRY
    # ═════════════════════════════════════════════════════════════════════════
    with tab_manual:
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px 20px 8px 20px; margin-bottom: 18px;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <span>1️⃣</span> Step 1: Supplier & Procurement Association
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 8px;">
                    Select an existing supplier or register a new vendor.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        existing_vendors = [v.name for v in ALL_VENDORS]
        db_vendors = [v["name"] for v in list_vendors()]
        all_vendor_names = sorted(list(set(existing_vendors + db_vendors)))

        col_v1, col_v2 = st.columns([2, 1])
        with col_v1:
            selected_vendor = st.selectbox(
                "Supplier / Vendor:",
                all_vendor_names + ["+ Register New Vendor..."],
                index=0,
            )

        is_new_vendor = selected_vendor == "+ Register New Vendor..."
        vendor_name_final = ""
        vendor_gstin_final = ""

        if is_new_vendor:
            col_nv1, col_nv2 = st.columns(2)
            with col_nv1:
                vendor_name_final = st.text_input("New Vendor Full Name *", placeholder="e.g. Apex Precision Tools Pvt Ltd").strip()
            with col_nv2:
                vendor_gstin_final = st.text_input("Vendor GSTIN (15 characters) *", placeholder="e.g. 27AAACA9999M1Z1").strip().upper()
        else:
            vendor_name_final = selected_vendor
            # Lookup GSTIN
            matching_syn = next((v for v in ALL_VENDORS if v.name == selected_vendor), None)
            if matching_syn:
                vendor_gstin_final = matching_syn.gstin
            else:
                db_v = next((v for v in list_vendors() if v["name"] == selected_vendor), None)
                vendor_gstin_final = db_v["gstin"] if db_v else "27AAACA9999M1Z1"
            st.caption(f"Verified GSTIN: `{vendor_gstin_final}`")

        # ─── PURCHASE ORDER (PO) ─────────────────────────────────────────────
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px 20px 8px 20px; margin: 20px 0 18px 0;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <span>2️⃣</span> Step 2: Contractual Purchase Order (PO)
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 8px;">
                    Associate with an existing authorized PO or create a new contractual baseline.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        all_pos = list_purchase_orders()
        po_options = ["+ Create New Purchase Order"] + [f"{p.po_number} — {p.item_description} (Qty: {p.quantity} @ ₹{p.unit_price_inr})" for p in all_pos]

        po_choice = st.selectbox("Associated Purchase Order:", po_options, index=0)
        is_new_po = po_choice.startswith("+ Create New Purchase Order")

        po_number_val = ""
        po_issue_date_val = date.today()
        po_expiry_date_val = date.today()
        po_item_desc_val = ""
        po_hsn_val = "8471"
        po_qty_val = 10
        po_price_val = 1000.0
        po_gst_rate_val = 0.18

        if not is_new_po:
            po_id_sel = po_choice.split(" — ")[0]
            existing_po = next((p for p in all_pos if p.po_number == po_id_sel), None)
            if existing_po:
                po_number_val = existing_po.po_number
                po_issue_date_val = existing_po.issue_date
                po_expiry_date_val = existing_po.valid_until
                po_item_desc_val = existing_po.item_description
                po_hsn_val = existing_po.hsn_code
                po_qty_val = existing_po.quantity
                po_price_val = float(existing_po.unit_price_inr)
                po_gst_rate_val = float(existing_po.gst_rate)
                st.info(f"Using Existing PO **{po_number_val}**: {po_item_desc_val} | Ordered: {po_qty_val} units @ ₹{po_price_val:,.2f} | Total: ₹{existing_po.total_inr:,.2f}")
        else:
            col_po1, col_po2, col_po3 = st.columns(3)
            with col_po1:
                po_number_val = st.text_input("PO Number *", value="PO-USR-2025-001").strip()
            with col_po2:
                po_issue_date_val = st.date_input("PO Issue Date", value=date.today())
            with col_po3:
                po_expiry_date_val = st.date_input("PO Expiry Date", value=date(date.today().year, 12, 31))

            col_poi1, col_poi2, col_poi3, col_poi4 = st.columns([2, 1, 1, 1])
            with col_poi1:
                po_item_desc_val = st.text_input("Item Description *", value="Industrial Ball Bearings 6205").strip()
            with col_poi2:
                po_hsn_val = st.text_input("HSN/SAC Code", value="8482").strip()
            with col_poi3:
                po_qty_val = st.number_input("Agreed Quantity", min_value=1, value=10, step=1)
            with col_poi4:
                po_price_val = st.number_input("Agreed Unit Price (INR)", min_value=0.01, value=1000.0, step=50.0)

            po_gst_choice = st.selectbox("PO Statutory GST Rate:", ["18% (Standard Goods)", "12% (Concessional)", "5% (Essential)", "28% (Luxury)", "0% (Nil)"], index=0)
            gst_map = {"18% (Standard Goods)": 0.18, "12% (Concessional)": 0.12, "5% (Essential)": 0.05, "28% (Luxury)": 0.28, "0% (Nil)": 0.0}
            po_gst_rate_val = gst_map[po_gst_choice]

            # PO Live Subtotal
            po_sub = Decimal(str(round(po_price_val * po_qty_val, 2)))
            po_tax = (po_sub * Decimal(str(po_gst_rate_val))).quantize(Decimal("0.01"))
            po_tot = po_sub + po_tax
            st.caption(f"PO Contracted Total: **₹{po_tot:,.2f}** (Subtotal: ₹{po_sub:,.2f} + GST: ₹{po_tax:,.2f})")

        # ─── GOODS RECEIPT NOTE (GRN) ─────────────────────────────────────────
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px 20px 8px 20px; margin: 20px 0 18px 0;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <span>3️⃣</span> Step 3: Goods Receipt Note (GRN)
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 8px;">
                    Record physical delivery verification from warehouse logs (optional for services).
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        grn_mode = st.radio(
            "Goods Receipt Mode:",
            ["Record Warehouse Delivery (Standard Goods)", "No Physical Delivery (Direct Billing / Services)"],
            index=0,
            horizontal=True,
        )

        grn_number_val = None
        grn_date_val = date.today()
        grn_qty_val = po_qty_val

        if grn_mode.startswith("Record Warehouse Delivery"):
            col_grn1, col_grn2, col_grn3 = st.columns(3)
            with col_grn1:
                grn_number_val = st.text_input("GRN Number *", value=f"GRN-{po_number_val}").strip()
            with col_grn2:
                grn_date_val = st.date_input("Receipt Date", value=date.today())
            with col_grn3:
                grn_qty_val = st.number_input("Physically Received Quantity", min_value=0, value=po_qty_val, step=1)

        # ─── SUPPLIER INVOICE ────────────────────────────────────────────────
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px 20px 8px 20px; margin: 20px 0 18px 0;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <span>4️⃣</span> Step 4: Incoming Supplier Invoice
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 8px;">
                    Enter the exact line-item values billed by the supplier on their tax invoice.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_inv1, col_inv2 = st.columns(2)
        with col_inv1:
            inv_number_val = st.text_input("Invoice Number *", value="INV-USR-2025-101").strip()
        with col_inv2:
            inv_date_val = st.date_input("Invoice Date", value=date.today())

        col_invi1, col_invi2, col_invi3, col_invi4 = st.columns([2, 1, 1, 1])
        with col_invi1:
            inv_desc_val = st.text_input("Billed Description", value=po_item_desc_val or "Industrial Ball Bearings 6205").strip()
        with col_invi2:
            inv_hsn_val = st.text_input("Billed HSN Code", value=po_hsn_val or "8482").strip()
        with col_invi3:
            inv_qty_val = st.number_input("Billed Quantity", min_value=1, value=po_qty_val, step=1)
        with col_invi4:
            inv_price_val = st.number_input("Billed Unit Price (INR)", min_value=0.01, value=float(po_price_val), step=20.0)

        inv_gst_choice = st.selectbox(
            "Billed GST Rate on Invoice:",
            ["18% (Standard Goods)", "12% (Concessional)", "5% (Essential)", "28% (Luxury)", "0% (Nil)"],
            index=0,
        )
        inv_gst_rate_val = gst_map[inv_gst_choice]

        inv_sub = Decimal(str(round(inv_price_val * inv_qty_val, 2)))
        inv_tax = (inv_sub * Decimal(str(inv_gst_rate_val))).quantize(Decimal("0.01"))
        inv_tot = inv_sub + inv_tax

        st.markdown(
            f"""
            <div style="background: rgba(30, 41, 59, 0.6); border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; margin: 14px 0;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #cbd5e1; font-size: 0.9rem;">Billed Invoice Payable Amount:</span>
                    <strong style="color: #10b981; font-size: 1.15rem;">₹{inv_tot:,.2f}</strong>
                </div>
                <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 4px;">
                    Subtotal: ₹{inv_sub:,.2f} | Billed Tax: ₹{inv_tax:,.2f} (@ {inv_gst_rate_val * 100:.0f}%)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        submit_intake = st.button("💾 Save All Documents & Run 3-Way Match", type="primary", use_container_width=True)

        if submit_intake:
            # Validations
            if not vendor_name_final:
                st.error("Validation Error: Vendor name is mandatory.")
                return
            if not po_number_val:
                st.error("Validation Error: Purchase order number is mandatory.")
                return
            if not inv_number_val:
                st.error("Validation Error: Invoice number is mandatory.")
                return

            try:
                # 1. Save Vendor
                save_vendor(vendor_name_final, vendor_gstin_final)

                # 2. Save PO
                po_obj = PurchaseOrder.create(
                    po_number=po_number_val,
                    vendor_name=vendor_name_final,
                    gstin=vendor_gstin_final,
                    issue_date=po_issue_date_val,
                    valid_until=po_expiry_date_val,
                    item_description=po_item_desc_val or "General Procurement Line",
                    hsn_code=po_hsn_val or "8471",
                    unit_price_inr=Decimal(str(round(po_price_val, 2))),
                    quantity=int(po_qty_val),
                    gst_rate=Decimal(str(po_gst_rate_val)),
                )
                save_purchase_order(po_obj)

                # 3. Save GRN (if applicable)
                grn_obj = None
                if grn_number_val:
                    grn_obj = GoodsReceiptNote(
                        grn_number=grn_number_val,
                        po_number=po_number_val,
                        receipt_date=grn_date_val,
                        received_quantity=int(grn_qty_val),
                        accepted_quantity=int(grn_qty_val),
                        rejected_quantity=0,
                        inspection_notes="Standard warehouse goods intake verification.",
                    )
                    save_goods_receipt(grn_obj)

                # 4. Save Invoice
                inv_obj = Invoice.create(
                    invoice_number=inv_number_val,
                    vendor_name=vendor_name_final,
                    gstin=vendor_gstin_final,
                    invoice_date=inv_date_val,
                    po_number=po_number_val,
                    grn_number=grn_number_val,
                    item_description=inv_desc_val or po_item_desc_val,
                    hsn_code=inv_hsn_val or po_hsn_val,
                    unit_price_inr=Decimal(str(round(inv_price_val, 2))),
                    quantity=int(inv_qty_val),
                    gst_rate=Decimal(str(inv_gst_rate_val)),
                )
                save_invoice(inv_obj, is_user_created=True)

                # 5. Run Match
                match_res = match_invoice(invoice=inv_obj, po=po_obj, grn=grn_obj)

                # 6. Render Feedback
                st.session_state["selected_invoice_id"] = inv_number_val
                st.success(f"🎉 **Invoice {inv_number_val} Successfully Saved to Persistent Ledger!**")

                if match_res.is_match:
                    st.markdown(
                        """
                        <div class="lm-callout" style="border-left: 4px solid #10b981; background: rgba(6, 78, 59, 0.4); padding: 14px; border-radius: 8px; margin: 12px 0;">
                            <strong style="color: #34d399;">✓ CLEAN THREE-WAY MATCH:</strong> All line items, prices, quantities, and GST rates reconcile with Purchase Order and Goods Receipt.
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"""
                        <div class="lm-callout" style="border-left: 4px solid #f59e0b; background: rgba(120, 53, 15, 0.4); padding: 14px; border-radius: 8px; margin: 12px 0;">
                            <strong style="color: #fbbf24;">⚠ EXCEPTION DETECTED ({match_res.exception_type.value}):</strong>
                            <div style="color: #fde68a; font-size: 0.9rem; margin-top: 4px;">{match_res.explanation}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("📋 View in Invoice Queue", use_container_width=True):
                        st.session_state["current_page"] = "Invoice Queue"
                        st.rerun()
                with col_btn2:
                    if st.button("🤖 Open in Resolution Workbench", type="primary", use_container_width=True):
                        st.session_state["current_page"] = "Resolution Workbench"
                        st.rerun()

            except Exception as e:
                st.error(f"Failed to record invoice: {e}")

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 2: CSV BATCH IMPORT
    # ═════════════════════════════════════════════════════════════════════════
    with tab_csv:
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px 20px 8px 20px; margin-bottom: 18px;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <span>📂</span> Batch Upload Invoices via CSV
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 8px;">
                    Upload structured supplier invoices. Each invoice line is matched against existing or newly imported POs.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        uploaded_file = st.file_uploader("Select Invoices CSV File", type=["csv"], help="Structured CSV matching the template.")

        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file)
                required_cols = [
                    "invoice_number", "vendor_name", "gstin", "invoice_date",
                    "po_number", "item_description", "hsn_code",
                    "unit_price_inr", "quantity", "gst_rate"
                ]
                missing = [c for c in required_cols if c not in df.columns]

                if missing:
                    st.error(f"Malformed CSV: Missing required columns: {missing}")
                else:
                    st.markdown(f"Found **{len(df)}** rows in uploaded file. Validating records...")

                    valid_records = []
                    validation_errors = []

                    for idx, row in df.iterrows():
                        row_num = idx + 2
                        try:
                            inv_num = str(row["invoice_number"]).strip()
                            v_name = str(row["vendor_name"]).strip()
                            gstin = str(row["gstin"]).strip().upper()
                            inv_dt = date.fromisoformat(str(row["invoice_date"]).strip())
                            po_num = str(row["po_number"]).strip()
                            grn_num = str(row["grn_number"]).strip() if "grn_number" in row and pd.notna(row["grn_number"]) else None
                            desc = str(row["item_description"]).strip()
                            hsn = str(row["hsn_code"]).strip()
                            price = Decimal(str(round(float(row["unit_price_inr"]), 2)))
                            qty = int(row["quantity"])
                            gst = Decimal(str(round(float(row["gst_rate"]), 4)))

                            if qty <= 0:
                                validation_errors.append(f"Row {row_num}: Quantity must be > 0")
                                continue
                            if price <= Decimal("0"):
                                validation_errors.append(f"Row {row_num}: Unit price must be > 0")
                                continue

                            inv_obj = Invoice.create(
                                invoice_number=inv_num,
                                vendor_name=v_name,
                                gstin=gstin,
                                invoice_date=inv_dt,
                                po_number=po_num,
                                grn_number=grn_num,
                                item_description=desc,
                                hsn_code=hsn,
                                unit_price_inr=price,
                                quantity=qty,
                                gst_rate=gst,
                            )
                            valid_records.append(inv_obj)

                        except Exception as ex:
                            validation_errors.append(f"Row {row_num}: Parse error ({ex})")

                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        st.metric("Valid Rows Parsed", len(valid_records))
                    with col_s2:
                        st.metric("Validation Errors", len(validation_errors))

                    if validation_errors:
                        with st.expander("⚠ View Validation Errors", expanded=True):
                            for err in validation_errors:
                                st.write(f"• {err}")

                    # Preview table
                    st.markdown("#### Preview Parsed Invoices:")
                    preview_data = [
                        {
                            "Invoice No": inv.invoice_number,
                            "Vendor": inv.vendor_name,
                            "PO Number": inv.po_number,
                            "Total Payable": f"₹{inv.total_inr:,.2f}",
                            "Date": inv.invoice_date.isoformat(),
                        }
                        for inv in valid_records
                    ]
                    st.dataframe(pd.DataFrame(preview_data), use_container_width=True)

                    if valid_records and st.button(f"📥 Confirm & Save {len(valid_records)} Valid Invoices to Persistent Store", type="primary"):
                        saved_count = 0
                        for inv in valid_records:
                            save_vendor(inv.vendor_name, inv.gstin)
                            save_invoice(inv, is_user_created=True)
                            saved_count += 1
                        st.success(f"✓ Successfully imported {saved_count} invoices into persistent storage!")
                        st.session_state["selected_invoice_id"] = valid_records[0].invoice_number

            except Exception as e:
                st.error(f"Failed to read CSV: {e}")

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 3: DOWNLOADABLE TEMPLATES
    # ═════════════════════════════════════════════════════════════════════════
    with tab_templates:
        st.markdown(
            """
            <div style="background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 16px 20px 8px 20px; margin-bottom: 18px;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #f8fafc; margin-bottom: 6px; display: flex; align-items: center; gap: 8px;">
                    <span>📋</span> Standard CSV Schema Templates
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 8px;">
                    Download verified sample CSV templates pre-populated with compliant column definitions and test rows.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown("##### 📄 Supplier Invoices Template")
            st.download_button(
                label="📥 Download sample_invoices.csv",
                data=SAMPLE_INVOICE_CSV_TEMPLATE,
                file_name="sample_invoices.csv",
                mime="text/csv",
                use_container_width=True,
            )
            st.code(SAMPLE_INVOICE_CSV_TEMPLATE, language="csv")

        with col_t2:
            st.markdown("##### 📄 Purchase Orders Template")
            st.download_button(
                label="📥 Download sample_purchase_orders.csv",
                data=SAMPLE_PO_CSV_TEMPLATE,
                file_name="sample_purchase_orders.csv",
                mime="text/csv",
                use_container_width=True,
            )
            st.code(SAMPLE_PO_CSV_TEMPLATE, language="csv")
