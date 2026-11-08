"""
data/synthetic.py
────────────────────────────────────────────────────────────────────────────────
Deterministic Synthetic AP Dataset Generator for Indian Business Enterprise.
Generates:
  1. 50 Historical Decision Records (dated 2024-06 to 2025-09 for memory seeding)
  2. 20 Held-Out Evaluation Invoices (dated 2025-10 to 2025-11 for benchmark queue)
Includes reproducible seeds, realistic Indian business attributes (INR, GSTIN, HSN),
and the documented Suryakant Engineering policy change around August 2025.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import random
from typing import Dict, List, Tuple

from agent.matcher import match_invoice
from data.models import (
    ApproverDecision,
    ApproverRole,
    Discrepancy,
    ExceptionType,
    ExpectedResolution,
    GoodsReceiptNote,
    HeldOutInvoice,
    HistoricalDecision,
    Invoice,
    MatchResult,
    PurchaseOrder,
)
from data.vendors import ALL_VENDORS, VENDORS_BY_SLUG


# Deterministic random seed for 100% reproducibility
DEFAULT_RANDOM_SEED = 42

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_FILE = os.path.join(DATA_DIR, "historical_decisions.json")
HELD_OUT_FILE = os.path.join(DATA_DIR, "held_out_invoices.json")
EVAL_LABELS_FILE = os.path.join(DATA_DIR, "held_out_evaluation_labels.json")


def generate_synthetic_datasets(seed: int = DEFAULT_RANDOM_SEED) -> Tuple[List[HistoricalDecision], List[HeldOutInvoice]]:
    """
    Generate deterministic synthetic datasets for LedgerMind.
    Returns:
        (historical_decisions, held_out_invoices)
    """
    random.seed(seed)

    history: List[HistoricalDecision] = []
    held_out: List[HeldOutInvoice] = []

    # Track paid invoice numbers to allow authentic duplicate invoice detection
    paid_invoice_registry: set[str] = set()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. PRABHAV INFOSYSTEMS PVT LTD (Slug: prabhav-infosystems)
    # Quirk: Unit price creeping overcharge (2% to 5% above contracted PO).
    # Approver: AP_MANAGER EDITS down to contracted PO rate.
    # ─────────────────────────────────────────────────────────────────────────
    prabhav = VENDORS_BY_SLUG["prabhav-infosystems"]

    # 6 Historical records
    for i in range(1, 7):
        seq = f"{i:03d}"
        inv_no = f"INV-PI-2024-{seq}" if i <= 3 else f"INV-PI-2025-{seq}"
        po_no = f"PO-IT-2024-{seq}" if i <= 3 else f"PO-IT-2025-{seq}"
        po_date = date(2024, 6 + i, 5) if i <= 6 else date(2025, i - 6, 5)
        inv_date = po_date + timedelta(days=random.randint(10, 20))

        contracted_rate = Decimal(str(random.choice([1500, 2000, 2500, 3000])))
        qty = random.choice([50, 75, 100, 120])
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=prabhav.name,
            gstin=prabhav.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Senior IT Consulting & Cloud DevOps Retainer",
            hsn_code=prabhav.standard_hsn,
            unit_price_inr=contracted_rate,
            quantity=qty,
            gst_rate=prabhav.standard_gst_rate,
        )

        # 2% to 4.5% creeping overcharge
        markup_pct = Decimal(str(random.choice([0.025, 0.03, 0.04, 0.045])))
        billed_rate = (contracted_rate * (Decimal("1.0") + markup_pct)).quantize(Decimal("0.01"))
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=prabhav.name,
            gstin=prabhav.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=None,  # Pure service retainer
            item_description="Senior IT Consulting & Cloud DevOps Retainer",
            hsn_code=prabhav.standard_hsn,
            unit_price_inr=billed_rate,
            quantity=qty,
            gst_rate=prabhav.standard_gst_rate,
        )

        match_res = match_invoice(invoice=invoice, po=po, grn=None, paid_invoice_numbers=paid_invoice_registry)
        paid_invoice_registry.add(inv_no)

        hist = HistoricalDecision(
            invoice=invoice,
            po=po,
            grn=None,
            match_result=match_res,
            decision=ApproverDecision.EDITED,
            approver_role=ApproverRole.AP_MANAGER,
            human_reason=f"Approved at PO contracted rate of ₹{po.total_inr:,.0f}; vendor advised of contracted pricing ceiling.",
            outcome_inr=po.total_inr,
            outcome_note=f"paid at contracted rate (saving ₹{(invoice.total_inr - po.total_inr):,.0f})",
            timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 11, 30, tzinfo=timezone.utc),
        )
        history.append(hist)

    # 3 Held-Out records for Prabhav
    for i in range(1, 4):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-PI-2025-{seq}"
        po_no = f"PO-IT-2025-{seq}"
        po_date = date(2025, 10, i * 3)
        inv_date = po_date + timedelta(days=12)

        contracted_rate = Decimal(str(random.choice([1800, 2200, 2800])))
        qty = random.choice([60, 80, 100])
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=prabhav.name,
            gstin=prabhav.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Senior IT Consulting & Cloud DevOps Retainer",
            hsn_code=prabhav.standard_hsn,
            unit_price_inr=contracted_rate,
            quantity=qty,
            gst_rate=prabhav.standard_gst_rate,
        )
        markup = Decimal(str(random.choice([0.03, 0.04])))
        billed_rate = (contracted_rate * (Decimal("1.0") + markup)).quantize(Decimal("0.01"))
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=prabhav.name,
            gstin=prabhav.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=None,
            item_description="Senior IT Consulting & Cloud DevOps Retainer",
            hsn_code=prabhav.standard_hsn,
            unit_price_inr=billed_rate,
            quantity=qty,
            gst_rate=prabhav.standard_gst_rate,
        )
        match_res = match_invoice(invoice=invoice, po=po, grn=None, paid_invoice_numbers=paid_invoice_registry)

        held_out.append(
            HeldOutInvoice(
                invoice=invoice,
                po=po,
                grn=None,
                match_result=match_res,
                expected_resolution=ExpectedResolution(
                    decision=ApproverDecision.EDITED,
                    amount_inr=po.total_inr,
                    reason=f"Approved at PO contracted rate of ₹{po.total_inr:,.0f}; overcharge eliminated.",
                ),
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. KAMALNATH SUPPLIES CO (Slug: kamalnath-supplies)
    # Quirk: Frequent duplicate invoice resubmissions.
    # Approver: AP_MANAGER REJECTS with "Duplicate invoice detected".
    # ─────────────────────────────────────────────────────────────────────────
    kamalnath = VENDORS_BY_SLUG["kamalnath-supplies"]

    # 6 Historical records
    for i in range(1, 7):
        seq = f"{i:03d}"
        base_inv_no = f"INV-KS-2024-{seq}" if i <= 3 else f"INV-KS-2025-{seq}"
        po_no = f"PO-PROC-2024-{seq}" if i <= 3 else f"PO-PROC-2025-{seq}"
        po_date = date(2024, 7 + i, 10) if i <= 5 else date(2025, i - 4, 10)
        inv_date = po_date + timedelta(days=15)

        rate = Decimal(str(random.choice([2500, 4500, 6000])))
        qty = random.choice([10, 20, 30])
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=kamalnath.name,
            gstin=kamalnath.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="High-Speed Ethernet Switches & Server Racks",
            hsn_code=kamalnath.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=kamalnath.standard_gst_rate,
        )

        grn = GoodsReceiptNote(
            grn_number=f"GRN-KS-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=10),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Delivered in good condition, hardware barcode verified.",
        )

        # Pre-seed this invoice number in registry to simulate it having been paid
        paid_invoice_registry.add(base_inv_no)

        # Now simulate the duplicate resubmission 14 days later
        dup_invoice = Invoice.create(
            invoice_number=base_inv_no,  # Duplicate
            vendor_name=kamalnath.name,
            gstin=kamalnath.gstin,
            invoice_date=inv_date + timedelta(days=14),
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="High-Speed Ethernet Switches & Server Racks",
            hsn_code=kamalnath.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=kamalnath.standard_gst_rate,
        )

        match_res = match_invoice(invoice=dup_invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)

        hist = HistoricalDecision(
            invoice=dup_invoice,
            po=po,
            grn=grn,
            match_result=match_res,
            decision=ApproverDecision.REJECTED,
            approver_role=ApproverRole.AP_MANAGER,
            human_reason=f"Duplicate invoice; original {base_inv_no} cleared in prior payment cycle. Vendor notified to cancel.",
            outcome_inr=Decimal("0.00"),
            outcome_note="paid ₹0 — duplicate rejected",
            timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 14, 15, tzinfo=timezone.utc),
        )
        history.append(hist)

    # 2 Held-Out records for Kamalnath
    for i in range(1, 3):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-KS-2025-{seq}"
        po_no = f"PO-PROC-2025-{seq}"
        po_date = date(2025, 10, i * 5)

        rate = Decimal("5000.00")
        qty = 15
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=kamalnath.name,
            gstin=kamalnath.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="High-Speed Ethernet Switches & Server Racks",
            hsn_code=kamalnath.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=kamalnath.standard_gst_rate,
        )
        grn = GoodsReceiptNote(
            grn_number=f"GRN-KS-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=8),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Hardware batch received.",
        )
        paid_invoice_registry.add(inv_no)

        dup_inv = Invoice.create(
            invoice_number=inv_no,
            vendor_name=kamalnath.name,
            gstin=kamalnath.gstin,
            invoice_date=po_date + timedelta(days=22),
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="High-Speed Ethernet Switches & Server Racks",
            hsn_code=kamalnath.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=kamalnath.standard_gst_rate,
        )
        match_res = match_invoice(invoice=dup_inv, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)

        held_out.append(
            HeldOutInvoice(
                invoice=dup_inv,
                po=po,
                grn=grn,
                match_result=match_res,
                expected_resolution=ExpectedResolution(
                    decision=ApproverDecision.REJECTED,
                    amount_inr=Decimal("0.00"),
                    reason=f"Duplicate invoice submission; previous record for {inv_no} already paid.",
                ),
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 3. DEVANSHI LOGISTICS LLP (Slug: devanshi-logistics)
    # Quirks:
    #   (a) Quantity shortfall on shipments (75% to 85% delivered).
    #   (b) HSN code discrepancy on freight services (996812 billed vs 996811 on PO).
    # Approver: AP_MANAGER APPROVES with partial payment / HSN clerical note.
    # ─────────────────────────────────────────────────────────────────────────
    devanshi = VENDORS_BY_SLUG["devanshi-logistics"]

    # 7 Historical records (4 shortfall, 3 pure HSN mismatch)
    for i in range(1, 8):
        seq = f"{i:03d}"
        inv_no = f"INV-DL-2024-{seq}" if i <= 3 else f"INV-DL-2025-{seq}"
        po_no = f"PO-LOG-2024-{seq}" if i <= 3 else f"PO-LOG-2025-{seq}"
        po_date = date(2024, 6 + i, 12) if i <= 6 else date(2025, i - 5, 12)
        inv_date = po_date + timedelta(days=14)

        rate = Decimal(str(random.choice([1200, 1500, 1800])))
        ordered_qty = random.choice([200, 300, 400])

        is_hsn_only = (i > 4)  # Records 5, 6, 7 are pure HSN mismatch with 100% quantity delivered

        if is_hsn_only:
            accepted_qty = ordered_qty  # 100% delivered
            po_hsn = "996811"           # Local freight transport
            inv_hsn = devanshi.standard_hsn  # 996812 Inter-state freight
        else:
            delivered_pct = random.choice([0.75, 0.80, 0.85])
            accepted_qty = int(ordered_qty * delivered_pct)
            po_hsn = devanshi.standard_hsn
            inv_hsn = devanshi.standard_hsn

        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=devanshi.name,
            gstin=devanshi.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Interstate Road Freight Transport (Full Truck Load)",
            hsn_code=po_hsn,
            unit_price_inr=rate,
            quantity=ordered_qty,
            gst_rate=devanshi.standard_gst_rate,
        )

        grn = GoodsReceiptNote(
            grn_number=f"GRN-DL-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=8),
            received_quantity=accepted_qty,
            accepted_quantity=accepted_qty,
            rejected_quantity=0,
            inspection_notes=f"Shipment intake verified: {accepted_qty} of {ordered_qty} metric ton units received.",
        )

        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=devanshi.name,
            gstin=devanshi.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Interstate Road Freight Transport (Full Truck Load)",
            hsn_code=inv_hsn,
            unit_price_inr=rate,
            quantity=ordered_qty,  # Invoiced for full ordered quantity
            gst_rate=devanshi.standard_gst_rate,
        )

        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)
        paid_invoice_registry.add(inv_no)

        if is_hsn_only:
            hist = HistoricalDecision(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                decision=ApproverDecision.APPROVED,
                approver_role=ApproverRole.AP_MANAGER,
                human_reason="HSN code difference (996812 billed vs 996811 PO) reviewed and approved as minor clerical classification delta; GST rates match.",
                outcome_inr=invoice.total_inr,
                outcome_note=f"paid full invoice ₹{invoice.total_inr:,.0f} with HSN clerical acceptance note",
                timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 16, 45, tzinfo=timezone.utc),
            )
        else:
            partial_subtotal = Decimal(accepted_qty) * rate
            partial_total = (partial_subtotal * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
            hist = HistoricalDecision(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                decision=ApproverDecision.APPROVED,
                approver_role=ApproverRole.AP_MANAGER,
                human_reason=f"Approved partial payment strictly for {accepted_qty} verified received units. Remaining {ordered_qty - accepted_qty} units cancelled.",
                outcome_inr=partial_total,
                outcome_note=f"paid ₹{partial_total:,.0f} for {accepted_qty}/{ordered_qty} units",
                timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 16, 45, tzinfo=timezone.utc),
            )
        history.append(hist)

    # 3 Held-Out records for Devanshi (2 shortfall, 1 pure HSN mismatch)
    for i in range(1, 4):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-DL-2025-{seq}"
        po_no = f"PO-LOG-2025-{seq}"
        po_date = date(2025, 10, i * 4)
        inv_date = po_date + timedelta(days=12)

        rate = Decimal("1600.00")
        ordered_qty = 250
        is_hsn_only = (i == 3)

        if is_hsn_only:
            accepted_qty = ordered_qty
            po_hsn = "996811"
            inv_hsn = devanshi.standard_hsn
        else:
            accepted_qty = 200  # 80% delivery
            po_hsn = devanshi.standard_hsn
            inv_hsn = devanshi.standard_hsn

        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=devanshi.name,
            gstin=devanshi.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Interstate Road Freight Transport (Full Truck Load)",
            hsn_code=po_hsn,
            unit_price_inr=rate,
            quantity=ordered_qty,
            gst_rate=devanshi.standard_gst_rate,
        )
        grn = GoodsReceiptNote(
            grn_number=f"GRN-DL-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=7),
            received_quantity=accepted_qty,
            accepted_quantity=accepted_qty,
            rejected_quantity=0,
            inspection_notes=f"Warehouse gate intake: {accepted_qty} pallets received.",
        )
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=devanshi.name,
            gstin=devanshi.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Interstate Road Freight Transport (Full Truck Load)",
            hsn_code=inv_hsn,
            unit_price_inr=rate,
            quantity=ordered_qty,
            gst_rate=devanshi.standard_gst_rate,
        )
        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)

        if is_hsn_only:
            held_out.append(
                HeldOutInvoice(
                    invoice=invoice,
                    po=po,
                    grn=grn,
                    match_result=match_res,
                    expected_resolution=ExpectedResolution(
                        decision=ApproverDecision.APPROVED,
                        amount_inr=invoice.total_inr,
                        reason="Approved full invoice amount; freight HSN difference accepted as minor clerical delta.",
                    ),
                )
            )
        else:
            partial_total = (Decimal(accepted_qty) * rate * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
            held_out.append(
                HeldOutInvoice(
                    invoice=invoice,
                    po=po,
                    grn=grn,
                    match_result=match_res,
                    expected_resolution=ExpectedResolution(
                        decision=ApproverDecision.APPROVED,
                        amount_inr=partial_total,
                        reason=f"Approved partial payment for delivered quantity of {accepted_qty} units (₹{partial_total:,.0f}).",
                    ),
                )
            )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. SURYAKANT ENGINEERING WORKS (Slug: suryakant-engineering)
    # Quirk: PO Expiry (invoices arrive 15-30 days after validity expires).
    # Approver Temporal Behavior Shift:
    #   - Before 2025-08-01: CFO ESCALATES and APPROVES with retrospective extension note.
    #   - On or After 2025-08-01: AP_MANAGER REJECTS per new 2025-Q3 procurement policy.
    # ─────────────────────────────────────────────────────────────────────────
    suryakant = VENDORS_BY_SLUG["suryakant-engineering"]
    POLICY_CHANGE_DATE = date(2025, 8, 1)

    # 7 Historical records (4 before policy change, 3 after)
    dates_suryakant = [
        date(2024, 7, 15),
        date(2024, 10, 20),
        date(2025, 1, 10),
        date(2025, 4, 15),  # End of pre-change records
        date(2025, 8, 5),   # Post-change record 1
        date(2025, 8, 25),  # Post-change record 2
        date(2025, 9, 15),  # Post-change record 3
    ]

    for i, base_date in enumerate(dates_suryakant, 1):
        seq = f"{i:03d}"
        inv_no = f"INV-SEW-2024-{seq}" if base_date.year == 2024 else f"INV-SEW-2025-{seq}"
        po_no = f"PO-ENG-2024-{seq}" if base_date.year == 2024 else f"PO-ENG-2025-{seq}"

        rate = Decimal(str(random.choice([15000, 25000, 35000])))
        qty = random.choice([5, 8, 12])
        valid_days = 30
        valid_until = base_date + timedelta(days=valid_days)
        # Invoice submitted 15-25 days AFTER po validity expired
        inv_date = valid_until + timedelta(days=random.randint(15, 25))

        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=suryakant.name,
            gstin=suryakant.gstin,
            issue_date=base_date,
            valid_until=valid_until,
            item_description="High-Tolerance CNC Machined Bearing Brackets",
            hsn_code=suryakant.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=suryakant.standard_gst_rate,
        )

        grn = GoodsReceiptNote(
            grn_number=f"GRN-SEW-{seq}",
            po_number=po_no,
            receipt_date=inv_date - timedelta(days=2),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Caliper inspection passed; components meet drawing specs.",
        )

        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=suryakant.name,
            gstin=suryakant.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="High-Tolerance CNC Machined Bearing Brackets",
            hsn_code=suryakant.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=suryakant.standard_gst_rate,
        )

        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)
        paid_invoice_registry.add(inv_no)

        if inv_date < POLICY_CHANGE_DATE:
            # Older policy: CFO escalation & approval
            hist = HistoricalDecision(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                decision=ApproverDecision.ESCALATED,
                approver_role=ApproverRole.CFO,
                human_reason="One-time grace extension granted by CFO due to critical component necessity. Retrospective extension approved.",
                outcome_inr=po.total_inr,
                outcome_note=f"paid ₹{po.total_inr:,.0f} under CFO executive exception",
                timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 17, 0, tzinfo=timezone.utc),
            )
        else:
            # New policy: AP_MANAGER rejection
            hist = HistoricalDecision(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                decision=ApproverDecision.REJECTED,
                approver_role=ApproverRole.AP_MANAGER,
                human_reason="Rejected per updated AP Policy 2025-Q3: expired PO requires fresh procurement requisition before processing.",
                outcome_inr=Decimal("0.00"),
                outcome_note="paid ₹0 — expired PO rejected under updated Q3 policy",
                timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 10, 15, tzinfo=timezone.utc),
            )
        history.append(hist)

    # 3 Held-Out records for Suryakant (All in October/November 2025 -> should follow REJECTION policy)
    for i in range(1, 4):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-SEW-2025-{seq}"
        po_no = f"PO-ENG-2025-{seq}"
        base_date = date(2025, 9, 15 + i * 5)
        valid_until = base_date + timedelta(days=30)
        inv_date = valid_until + timedelta(days=18)

        rate = Decimal("20000.00")
        qty = 10
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=suryakant.name,
            gstin=suryakant.gstin,
            issue_date=base_date,
            valid_until=valid_until,
            item_description="High-Tolerance CNC Machined Bearing Brackets",
            hsn_code=suryakant.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=suryakant.standard_gst_rate,
        )
        grn = GoodsReceiptNote(
            grn_number=f"GRN-SEW-{seq}",
            po_number=po_no,
            receipt_date=inv_date - timedelta(days=2),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Delivered to assembly floor.",
        )
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=suryakant.name,
            gstin=suryakant.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="High-Tolerance CNC Machined Bearing Brackets",
            hsn_code=suryakant.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=suryakant.standard_gst_rate,
        )
        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)

        held_out.append(
            HeldOutInvoice(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                expected_resolution=ExpectedResolution(
                    decision=ApproverDecision.REJECTED,
                    amount_inr=Decimal("0.00"),
                    reason="Rejected per current AP Policy 2025-Q3: expired PO requires fresh procurement requisition before processing.",
                ),
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 5. NARMADA PHARMA DISTRIBUTORS (Slug: narmada-pharma)
    # Quirk: GST Rate Error (applies 12% instead of statutory 18%).
    # Approver: FINANCE_CONTROLLER REJECTS to prevent input tax credit (ITC) loss.
    # ─────────────────────────────────────────────────────────────────────────
    narmada = VENDORS_BY_SLUG["narmada-pharma"]

    # 6 Historical records
    for i in range(1, 7):
        seq = f"{i:03d}"
        inv_no = f"INV-NPD-2024-{seq}" if i <= 3 else f"INV-NPD-2025-{seq}"
        po_no = f"PO-PHARM-2024-{seq}" if i <= 3 else f"PO-PHARM-2025-{seq}"
        po_date = date(2024, 7 + i, 18) if i <= 5 else date(2025, i - 4, 18)
        inv_date = po_date + timedelta(days=12)

        rate = Decimal(str(random.choice([800, 1200, 1600])))
        qty = random.choice([100, 150, 200])
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=narmada.name,
            gstin=narmada.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Diagnostic Reagent Assay Kits & Laboratory Glassware",
            hsn_code=narmada.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=Decimal("0.18"),  # Contracted 18%
        )

        grn = GoodsReceiptNote(
            grn_number=f"GRN-NPD-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=8),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Cold-chain temperature logs intact, reagents approved.",
        )

        # Invoiced at incorrect 12% GST
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=narmada.name,
            gstin=narmada.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Diagnostic Reagent Assay Kits & Laboratory Glassware",
            hsn_code=narmada.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=Decimal("0.12"),  # Wrong rate
        )

        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)
        paid_invoice_registry.add(inv_no)

        hist = HistoricalDecision(
            invoice=invoice,
            po=po,
            grn=grn,
            match_result=match_res,
            decision=ApproverDecision.REJECTED,
            approver_role=ApproverRole.FINANCE_CONTROLLER,
            human_reason="Statutory GST rate mismatch (12% invoiced vs 18% applicable). Cannot claim ITC on incorrect invoice; returned for credit note / revised tax invoice.",
            outcome_inr=Decimal("0.00"),
            outcome_note="paid ₹0 — rejected for revised tax invoice to preserve ITC",
            timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 15, 30, tzinfo=timezone.utc),
        )
        history.append(hist)

    # 2 Held-Out records for Narmada
    for i in range(1, 3):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-NPD-2025-{seq}"
        po_no = f"PO-PHARM-2025-{seq}"
        po_date = date(2025, 10, i * 6)
        inv_date = po_date + timedelta(days=10)

        rate = Decimal("1500.00")
        qty = 100
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=narmada.name,
            gstin=narmada.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Diagnostic Reagent Assay Kits & Laboratory Glassware",
            hsn_code=narmada.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=Decimal("0.18"),
        )
        grn = GoodsReceiptNote(
            grn_number=f"GRN-NPD-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=6),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Approved lab assay inventory.",
        )
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=narmada.name,
            gstin=narmada.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Diagnostic Reagent Assay Kits & Laboratory Glassware",
            hsn_code=narmada.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=Decimal("0.12"),  # Wrong rate
        )
        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)

        held_out.append(
            HeldOutInvoice(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                expected_resolution=ExpectedResolution(
                    decision=ApproverDecision.REJECTED,
                    amount_inr=Decimal("0.00"),
                    reason="Statutory GST rate error: 12% billed vs 18% statutory. Ineligible for GSTR-2B input credit; rejected for replacement invoice.",
                ),
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 6. BHAVNA TEXTILE TRADERS (Slug: bhavna-textiles)
    # Quirk: Minor unit price discrepancy (1% to 3% above PO) on fabric yardage.
    # Approver: AP_MANAGER APPROVES with GL variance adjustment.
    # ─────────────────────────────────────────────────────────────────────────
    bhavna = VENDORS_BY_SLUG["bhavna-textiles"]

    # 6 Historical records
    for i in range(1, 7):
        seq = f"{i:03d}"
        inv_no = f"INV-BTT-2024-{seq}" if i <= 3 else f"INV-BTT-2025-{seq}"
        po_no = f"PO-TEX-2024-{seq}" if i <= 3 else f"PO-TEX-2025-{seq}"
        po_date = date(2024, 6 + i, 20) if i <= 6 else date(2025, i - 5, 20)
        inv_date = po_date + timedelta(days=14)

        base_rate = Decimal(str(random.choice([250, 350, 450])))
        qty = random.choice([500, 800, 1000])
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=bhavna.name,
            gstin=bhavna.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Heavy Cotton Canvas & Safety Uniform Yardage",
            hsn_code=bhavna.standard_hsn,
            unit_price_inr=base_rate,
            quantity=qty,
            gst_rate=bhavna.standard_gst_rate,  # 5%
        )

        grn = GoodsReceiptNote(
            grn_number=f"GRN-BTT-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=10),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Fabric rolls received, thread density verified.",
        )

        # 1.5% to 2.8% price variance
        variance_pct = Decimal(str(random.choice([0.015, 0.02, 0.025])))
        billed_rate = (base_rate * (Decimal("1.0") + variance_pct)).quantize(Decimal("0.01"))
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=bhavna.name,
            gstin=bhavna.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Heavy Cotton Canvas & Safety Uniform Yardage",
            hsn_code=bhavna.standard_hsn,
            unit_price_inr=billed_rate,
            quantity=qty,
            gst_rate=bhavna.standard_gst_rate,
        )

        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)
        paid_invoice_registry.add(inv_no)

        delta = invoice.total_inr - po.total_inr
        hist = HistoricalDecision(
            invoice=invoice,
            po=po,
            grn=grn,
            match_result=match_res,
            decision=ApproverDecision.APPROVED,
            approver_role=ApproverRole.AP_MANAGER,
            human_reason=f"Approved with ₹{delta:,.0f} cost-center variance booked to textile cotton indexation tolerance.",
            outcome_inr=invoice.total_inr,
            outcome_note=f"paid full invoice ₹{invoice.total_inr:,.0f} with indexation variance",
            timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 12, 0, tzinfo=timezone.utc),
        )
        history.append(hist)

    # 2 Held-Out records for Bhavna
    for i in range(1, 3):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-BTT-2025-{seq}"
        po_no = f"PO-TEX-2025-{seq}"
        po_date = date(2025, 10, i * 7)
        inv_date = po_date + timedelta(days=11)

        base_rate = Decimal("300.00")
        qty = 600
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=bhavna.name,
            gstin=bhavna.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Heavy Cotton Canvas & Safety Uniform Yardage",
            hsn_code=bhavna.standard_hsn,
            unit_price_inr=base_rate,
            quantity=qty,
            gst_rate=bhavna.standard_gst_rate,
        )
        grn = GoodsReceiptNote(
            grn_number=f"GRN-BTT-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=8),
            received_quantity=qty,
            accepted_quantity=qty,
            rejected_quantity=0,
            inspection_notes="Material yardage measured and approved.",
        )
        billed_rate = Decimal("306.00")  # 2% variance
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=bhavna.name,
            gstin=bhavna.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Heavy Cotton Canvas & Safety Uniform Yardage",
            hsn_code=bhavna.standard_hsn,
            unit_price_inr=billed_rate,
            quantity=qty,
            gst_rate=bhavna.standard_gst_rate,
        )
        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)

        held_out.append(
            HeldOutInvoice(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                expected_resolution=ExpectedResolution(
                    decision=ApproverDecision.APPROVED,
                    amount_inr=invoice.total_inr,
                    reason="Approved full invoice amount with indexation tolerance variance.",
                ),
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 7. TRIVENI AGRO PROCESSORS (Slug: triveni-agro)
    # Quirk: Delivered quantity rounded down to nearest 50 kg bag unit.
    # Approver: AP_MANAGER APPROVES after GRN quantity amendment.
    # ─────────────────────────────────────────────────────────────────────────
    triveni = VENDORS_BY_SLUG["triveni-agro"]

    # 6 Historical records
    for i in range(1, 7):
        seq = f"{i:03d}"
        inv_no = f"INV-TAP-2024-{seq}" if i <= 3 else f"INV-TAP-2025-{seq}"
        po_no = f"PO-AGRO-2024-{seq}" if i <= 3 else f"PO-AGRO-2025-{seq}"
        po_date = date(2024, 7 + i, 22) if i <= 5 else date(2025, i - 4, 22)
        inv_date = po_date + timedelta(days=12)

        rate = Decimal(str(random.choice([60, 80, 100])))
        ordered_kg = random.choice([1000, 1500, 2000])  # in kg
        # Rounded to 50kg bag (e.g. 50kg or 100kg short)
        shortfall_kg = random.choice([50, 100])
        delivered_kg = ordered_kg - shortfall_kg

        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=triveni.name,
            gstin=triveni.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Industrial Food-Grade Corn Starch & Dextrose Bags",
            hsn_code=triveni.standard_hsn,
            unit_price_inr=rate,
            quantity=ordered_kg,
            gst_rate=triveni.standard_gst_rate,  # 12%
        )

        grn = GoodsReceiptNote(
            grn_number=f"GRN-TAP-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=8),
            received_quantity=delivered_kg,
            accepted_quantity=delivered_kg,
            rejected_quantity=0,
            inspection_notes=f"Weighbridge slip attached: {delivered_kg} kg verified in intact 50kg bags.",
        )

        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=triveni.name,
            gstin=triveni.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Industrial Food-Grade Corn Starch & Dextrose Bags",
            hsn_code=triveni.standard_hsn,
            unit_price_inr=rate,
            quantity=ordered_kg,  # Invoiced for full ordered weight
            gst_rate=triveni.standard_gst_rate,
        )

        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)
        paid_invoice_registry.add(inv_no)

        delivered_total = (Decimal(delivered_kg) * rate * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
        hist = HistoricalDecision(
            invoice=invoice,
            po=po,
            grn=grn,
            match_result=match_res,
            decision=ApproverDecision.APPROVED,
            approver_role=ApproverRole.AP_MANAGER,
            human_reason=f"Approved for actual delivered weight of {delivered_kg} kg; debit note raised for {shortfall_kg} kg packing unit shortfall.",
            outcome_inr=delivered_total,
            outcome_note=f"paid ₹{delivered_total:,.0f} for actual delivered {delivered_kg} kg",
            timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 14, 0, tzinfo=timezone.utc),
        )
        history.append(hist)

    # 3 Held-Out records for Triveni
    for i in range(1, 4):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-TAP-2025-{seq}"
        po_no = f"PO-AGRO-2025-{seq}"
        po_date = date(2025, 10, i * 4)
        inv_date = po_date + timedelta(days=9)

        rate = Decimal("90.00")
        ordered_kg = 1200
        delivered_kg = 1150  # 50 kg short
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=triveni.name,
            gstin=triveni.gstin,
            issue_date=po_date,
            valid_until=po_date + timedelta(days=60),
            item_description="Industrial Food-Grade Corn Starch & Dextrose Bags",
            hsn_code=triveni.standard_hsn,
            unit_price_inr=rate,
            quantity=ordered_kg,
            gst_rate=triveni.standard_gst_rate,
        )
        grn = GoodsReceiptNote(
            grn_number=f"GRN-TAP-{seq}",
            po_number=po_no,
            receipt_date=po_date + timedelta(days=6),
            received_quantity=delivered_kg,
            accepted_quantity=delivered_kg,
            rejected_quantity=0,
            inspection_notes=f"Weighbridge: {delivered_kg} kg accepted.",
        )
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=triveni.name,
            gstin=triveni.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=grn.grn_number,
            item_description="Industrial Food-Grade Corn Starch & Dextrose Bags",
            hsn_code=triveni.standard_hsn,
            unit_price_inr=rate,
            quantity=ordered_kg,
            gst_rate=triveni.standard_gst_rate,
        )
        match_res = match_invoice(invoice=invoice, po=po, grn=grn, paid_invoice_numbers=paid_invoice_registry)

        delivered_total = (Decimal(delivered_kg) * rate * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
        held_out.append(
            HeldOutInvoice(
                invoice=invoice,
                po=po,
                grn=grn,
                match_result=match_res,
                expected_resolution=ExpectedResolution(
                    decision=ApproverDecision.APPROVED,
                    amount_inr=delivered_total,
                    reason=f"Approved for delivered quantity of {delivered_kg} kg (₹{delivered_total:,.0f}).",
                ),
            )
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 8. CHINTAMANI TECH SOLUTIONS (Slug: chintamani-tech)
    # Quirk: Emergency service invoices billed against expired PO contracts (PO_EXPIRED).
    # Approver: AP_MANAGER ESCALATES to FINANCE_CONTROLLER who APPROVES.
    # ─────────────────────────────────────────────────────────────────────────
    chintamani = VENDORS_BY_SLUG["chintamani-tech"]

    # 6 Historical records
    for i in range(1, 7):
        seq = f"{i:03d}"
        inv_no = f"INV-CTS-2024-{seq}" if i <= 3 else f"INV-CTS-2025-{seq}"
        po_no = f"PO-EMRG-2024-{seq}" if i <= 3 else f"PO-EMRG-2025-{seq}"
        inv_date = date(2024, 6 + i, 25) if i <= 6 else date(2025, i - 5, 25)
        # PO was issued earlier and expired 10-30 days BEFORE invoice date
        days_expired = random.randint(10, 30)
        po_date = inv_date - timedelta(days=days_expired + 30)
        valid_until = inv_date - timedelta(days=days_expired)

        rate = Decimal(str(random.choice([45000, 65000, 85000])))
        qty = 1
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=chintamani.name,
            gstin=chintamani.gstin,
            issue_date=po_date,
            valid_until=valid_until,
            item_description="Emergency Cloud Database Incident Restoration Retainer",
            hsn_code=chintamani.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=chintamani.standard_gst_rate,
        )

        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=chintamani.name,
            gstin=chintamani.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=None,
            item_description="Emergency Cloud Database Incident Restoration Retainer",
            hsn_code=chintamani.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=chintamani.standard_gst_rate,
        )

        match_res = match_invoice(invoice=invoice, po=po, grn=None, paid_invoice_numbers=paid_invoice_registry)
        paid_invoice_registry.add(inv_no)

        hist = HistoricalDecision(
            invoice=invoice,
            po=po,
            grn=None,
            match_result=match_res,
            decision=ApproverDecision.APPROVED,
            approver_role=ApproverRole.FINANCE_CONTROLLER,
            human_reason=f"Approved emergency infrastructure support despite expired PO validity ({days_expired} days overdue); Controller granted retrospective validity extension.",
            outcome_inr=invoice.total_inr,
            outcome_note=f"paid ₹{invoice.total_inr:,.0f} under expired PO emergency approval protocol",
            timestamp=datetime(inv_date.year, inv_date.month, inv_date.day, 18, 30, tzinfo=timezone.utc),
        )
        history.append(hist)

    # 2 Held-Out records for Chintamani
    for i in range(1, 3):
        seq = f"{100 + i:03d}"
        inv_no = f"INV-CTS-2025-{seq}"
        po_no = f"PO-EMRG-2025-{seq}"
        inv_date = date(2025, 10, i * 8)
        days_expired = 15
        po_date = inv_date - timedelta(days=45)
        valid_until = inv_date - timedelta(days=days_expired)

        rate = Decimal("75000.00")
        qty = 1
        po = PurchaseOrder.create(
            po_number=po_no,
            vendor_name=chintamani.name,
            gstin=chintamani.gstin,
            issue_date=po_date,
            valid_until=valid_until,
            item_description="Emergency Cloud Database Incident Restoration Retainer",
            hsn_code=chintamani.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=chintamani.standard_gst_rate,
        )
        invoice = Invoice.create(
            invoice_number=inv_no,
            vendor_name=chintamani.name,
            gstin=chintamani.gstin,
            invoice_date=inv_date,
            po_number=po_no,
            grn_number=None,
            item_description="Emergency Cloud Database Incident Restoration Retainer",
            hsn_code=chintamani.standard_hsn,
            unit_price_inr=rate,
            quantity=qty,
            gst_rate=chintamani.standard_gst_rate,
        )
        match_res = match_invoice(invoice=invoice, po=po, grn=None, paid_invoice_numbers=paid_invoice_registry)

        held_out.append(
            HeldOutInvoice(
                invoice=invoice,
                po=po,
                grn=None,
                match_result=match_res,
                expected_resolution=ExpectedResolution(
                    exception_type=ExceptionType.PO_EXPIRED,
                    decision=ApproverDecision.APPROVED,
                    amount_inr=invoice.total_inr,
                    reason=f"Approved emergency spend under retrospective Controller validity extension (PO expired by {days_expired} days).",
                ),
            )
        )

    # Sort history chronologically by timestamp
    history.sort(key=lambda h: h.timestamp)

    return history, held_out


def save_synthetic_datasets(
    history: List[HistoricalDecision],
    held_out: List[HeldOutInvoice],
    historical_path: str = HISTORICAL_FILE,
    held_out_path: str = HELD_OUT_FILE,
    labels_path: str = EVAL_LABELS_FILE,
) -> None:
    """Save generated datasets into designated JSON files."""
    os.makedirs(os.path.dirname(historical_path), exist_ok=True)

    # 1. Historical decisions
    hist_dicts = [h.model_dump(mode="json") for h in history]
    with open(historical_path, "w", encoding="utf-8") as f:
        json.dump(hist_dicts, f, indent=2, default=str)

    # 2. Held-out invoices
    held_out_dicts = [h.model_dump(mode="json") for h in held_out]
    with open(held_out_path, "w", encoding="utf-8") as f:
        json.dump(held_out_dicts, f, indent=2, default=str)

    # 3. Ground truth evaluation labels (kept separate)
    labels = {
        h.invoice.invoice_number: h.expected_resolution.model_dump(mode="json")
        for h in held_out
    }
    with open(labels_path, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, default=str)


def load_historical_decisions(path: str = HISTORICAL_FILE) -> List[HistoricalDecision]:
    """Load historical decisions from persistent storage."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [HistoricalDecision.model_validate(item) for item in raw]


def load_held_out_invoices(path: str = HELD_OUT_FILE) -> List[HeldOutInvoice]:
    """Load held-out evaluation invoices from persistent storage."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [HeldOutInvoice.model_validate(item) for item in raw]


def load_evaluation_labels(path: str = EVAL_LABELS_FILE) -> Dict[str, ExpectedResolution]:
    """Load ground truth evaluation labels."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {k: ExpectedResolution.model_validate(v) for k, v in raw.items()}


if __name__ == "__main__":
    print("Generating synthetic datasets with seed=42...")
    h_data, ho_data = generate_synthetic_datasets(seed=DEFAULT_RANDOM_SEED)
    save_synthetic_datasets(h_data, ho_data)
    print(f"Generated {len(h_data)} historical decisions -> {HISTORICAL_FILE}")
    print(f"Generated {len(ho_data)} held-out evaluation invoices -> {HELD_OUT_FILE}")
    print(f"Generated ground-truth labels -> {EVAL_LABELS_FILE}")
