"""
agent/matcher.py
────────────────────────────────────────────────────────────────────────────────
Deterministic Three-Way Matching Engine for LedgerMind.
Reconciles Supplier Invoice against Purchase Order and Goods Receipt Note.
Detects:
  - PRICE_MISMATCH
  - QUANTITY_SHORTFALL
  - DUPLICATE_INVOICE
  - GST_RATE_ERROR
  - PO_EXPIRED
  - HSN_MISMATCH
Pure Python logic without LLM hallucinations or vendor-specific heuristics.
"""

from decimal import Decimal
from typing import Collection, List, Optional
from data.models import Discrepancy, ExceptionType, GoodsReceiptNote, Invoice, MatchResult, PurchaseOrder


# Operational severity hierarchy for selecting the primary exception
EXCEPTION_PRIORITY = [
    ExceptionType.DUPLICATE_INVOICE,
    ExceptionType.PO_EXPIRED,
    ExceptionType.GST_RATE_ERROR,
    ExceptionType.QUANTITY_SHORTFALL,
    ExceptionType.PRICE_MISMATCH,
    ExceptionType.HSN_MISMATCH,
]


def match_invoice(
    invoice: Invoice,
    po: PurchaseOrder,
    grn: Optional[GoodsReceiptNote] = None,
    paid_invoice_numbers: Optional[Collection[str]] = None,
) -> MatchResult:
    """
    Perform deterministic 3-way matching.

    Args:
        invoice: Billed supplier invoice.
        po: Contracted purchase order.
        grn: Warehouse goods receipt note (optional for pure services).
        paid_invoice_numbers: Collection of previously processed invoice numbers to detect duplicates.

    Returns:
        MatchResult with match status, primary exception, list of all discrepancies, and explanations.
    """
    discrepancies: List[Discrepancy] = []

    # 1. DUPLICATE INVOICE CHECK
    if paid_invoice_numbers:
        norm_inv = invoice.invoice_number.strip().upper()
        norm_paid = {str(p).strip().upper() for p in paid_invoice_numbers}
        if norm_inv in norm_paid:
            discrepancies.append(
                Discrepancy(
                    exception_type=ExceptionType.DUPLICATE_INVOICE,
                    field="invoice_number",
                    invoice_value=invoice.invoice_number,
                    expected_value="NOT_PREVIOUSLY_PAID",
                    delta_inr=invoice.total_inr,
                    message=(
                        f"Duplicate invoice submission: invoice number {invoice.invoice_number} "
                        f"has already been processed / cleared for payment in the ledger."
                    ),
                )
            )

    # 2. PO EXPIRY CHECK
    if invoice.invoice_date > po.valid_until:
        days_late = (invoice.invoice_date - po.valid_until).days
        discrepancies.append(
            Discrepancy(
                exception_type=ExceptionType.PO_EXPIRED,
                field="invoice_date",
                invoice_value=str(invoice.invoice_date),
                expected_value=str(po.valid_until),
                delta_inr=invoice.total_inr,
                message=(
                    f"Purchase order {po.po_number} expired on {po.valid_until}. "
                    f"Invoice dated {invoice.invoice_date} submitted {days_late} days after validity expiry."
                ),
            )
        )

    # 3. HSN / SAC CODE MISMATCH
    inv_hsn = invoice.hsn_code.strip()
    po_hsn = po.hsn_code.strip()
    if inv_hsn != po_hsn:
        discrepancies.append(
            Discrepancy(
                exception_type=ExceptionType.HSN_MISMATCH,
                field="hsn_code",
                invoice_value=inv_hsn,
                expected_value=po_hsn,
                delta_inr=None,
                message=(
                    f"HSN code on invoice ({inv_hsn}) does not match PO contracted HSN ({po_hsn})."
                ),
            )
        )

    # 4. GST STATUTORY RATE MISMATCH
    if invoice.gst_rate != po.gst_rate:
        expected_gst_amount = (invoice.total_excl_tax_inr * po.gst_rate).quantize(Decimal("0.01"))
        tax_delta = (invoice.gst_amount_inr - expected_gst_amount).quantize(Decimal("0.01"))
        discrepancies.append(
            Discrepancy(
                exception_type=ExceptionType.GST_RATE_ERROR,
                field="gst_rate",
                invoice_value=invoice.gst_rate,
                expected_value=po.gst_rate,
                delta_inr=tax_delta,
                message=(
                    f"Statutory GST rate mismatch: invoice applied {invoice.gst_rate * 100:.1f}% "
                    f"vs PO contracted rate {po.gst_rate * 100:.1f}% (tax delta: ₹{tax_delta:+,.2f})."
                ),
            )
        )

    # 5. QUANTITY SHORTFALL (PHYSICAL GRN VS INVOICE)
    if grn is not None:
        if grn.accepted_quantity < invoice.quantity:
            shortfall_units = invoice.quantity - grn.accepted_quantity
            # Financial impact = shortfall units * po unit price * (1 + po_tax_rate)
            shortfall_val_subtotal = Decimal(shortfall_units) * po.unit_price_inr
            shortfall_val_total = (shortfall_val_subtotal * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
            discrepancies.append(
                Discrepancy(
                    exception_type=ExceptionType.QUANTITY_SHORTFALL,
                    field="quantity",
                    invoice_value=invoice.quantity,
                    expected_value=grn.accepted_quantity,
                    delta_inr=shortfall_val_total,
                    message=(
                        f"Quantity shortfall: GRN {grn.grn_number} accepted {grn.accepted_quantity} units "
                        f"vs invoice billed {invoice.quantity} units (shortfall of {shortfall_units} units; "
                        f"disputed value ₹{shortfall_val_total:,.2f})."
                    ),
                )
            )

    # 6. PRICE MISMATCH (UNIT RATE & TOTAL SUB-TOTAL)
    if invoice.unit_price_inr > po.unit_price_inr:
        unit_delta = invoice.unit_price_inr - po.unit_price_inr
        overcharge_subtotal = unit_delta * Decimal(invoice.quantity)
        overcharge_total = (overcharge_subtotal * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
        pct_over = ((unit_delta / po.unit_price_inr) * 100).quantize(Decimal("0.1"))
        discrepancies.append(
            Discrepancy(
                exception_type=ExceptionType.PRICE_MISMATCH,
                field="unit_price_inr",
                invoice_value=invoice.unit_price_inr,
                expected_value=po.unit_price_inr,
                delta_inr=overcharge_total,
                message=(
                    f"Price mismatch: billed unit rate ₹{invoice.unit_price_inr:,.2f} exceeds PO rate "
                    f"₹{po.unit_price_inr:,.2f} by ₹{unit_delta:,.2f} (+{pct_over}% overcharge; "
                    f"gross discrepancy ₹{overcharge_total:,.2f})."
                ),
            )
        )

    # Assemble MatchResult
    if not discrepancies:
        return MatchResult(
            is_match=True,
            exception_type=ExceptionType.NONE,
            primary_discrepancy=None,
            all_discrepancies=[],
            invoice_number=invoice.invoice_number,
            po_number=po.po_number,
            vendor_name=invoice.vendor_name,
            invoice_amount_inr=invoice.total_inr,
            expected_amount_inr=po.total_inr,
            explanation="3-way match passed cleanly: invoice, PO, and goods receipt reconcile perfectly.",
        )

    # Determine primary discrepancy according to operational severity hierarchy
    primary: Optional[Discrepancy] = None
    for p_type in EXCEPTION_PRIORITY:
        for d in discrepancies:
            if d.exception_type == p_type:
                primary = d
                break
        if primary:
            break

    if primary is None:
        primary = discrepancies[0]

    # Calculate expected amount based on primary discrepancy
    expected_amount = po.total_inr
    if primary.exception_type == ExceptionType.DUPLICATE_INVOICE:
        expected_amount = Decimal("0.00")
    elif primary.exception_type == ExceptionType.QUANTITY_SHORTFALL and grn is not None:
        # Expected is accepted quantity * PO unit rate + tax
        acc_subtotal = Decimal(grn.accepted_quantity) * po.unit_price_inr
        expected_amount = (acc_subtotal * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
    elif primary.exception_type == ExceptionType.PRICE_MISMATCH:
        # Expected is invoice quantity * PO unit rate + tax
        expected_subtotal = Decimal(invoice.quantity) * po.unit_price_inr
        expected_amount = (expected_subtotal * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))
    elif primary.exception_type == ExceptionType.GST_RATE_ERROR:
        # Expected is invoice subtotal with PO GST rate
        expected_amount = (invoice.total_excl_tax_inr * (Decimal("1.0") + po.gst_rate)).quantize(Decimal("0.01"))

    # Summary explanation
    if len(discrepancies) == 1:
        explanation = primary.message
    else:
        explanation = (
            f"Multiple discrepancies detected (primary: {primary.exception_type.value}): "
            + "; ".join(d.message for d in discrepancies)
        )

    return MatchResult(
        is_match=False,
        exception_type=primary.exception_type,
        primary_discrepancy=primary,
        all_discrepancies=discrepancies,
        invoice_number=invoice.invoice_number,
        po_number=po.po_number,
        vendor_name=invoice.vendor_name,
        invoice_amount_inr=invoice.total_inr,
        expected_amount_inr=expected_amount,
        explanation=explanation,
    )

