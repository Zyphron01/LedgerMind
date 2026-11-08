"""
data/models.py
────────────────────────────────────────────────────────────────────────────────
Core Pydantic models for LedgerMind Accounts-Payable Exception-Handling.
Covers Invoices, Purchase Orders, Goods Receipt Notes, Exceptions, Decisions,
and Held-Out Evaluation data models for Indian Business AP Workflows.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


# ═════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═════════════════════════════════════════════════════════════════════════════

class ExceptionType(str, Enum):
    """The six canonical 3-way match exception types in AP processing."""
    PRICE_MISMATCH      = "PRICE_MISMATCH"
    QUANTITY_SHORTFALL  = "QUANTITY_SHORTFALL"
    DUPLICATE_INVOICE   = "DUPLICATE_INVOICE"
    GST_RATE_ERROR      = "GST_RATE_ERROR"
    PO_EXPIRED          = "PO_EXPIRED"
    HSN_MISMATCH        = "HSN_MISMATCH"
    NONE                = "NONE"


class ApproverRole(str, Enum):
    """Organizational roles that review and resolve AP exceptions."""
    AP_CLERK            = "AP_CLERK"
    AP_MANAGER          = "AP_MANAGER"
    FINANCE_CONTROLLER  = "FINANCE_CONTROLLER"
    CFO                 = "CFO"
    PROCUREMENT_LEAD    = "PROCUREMENT_LEAD"


class ApproverDecision(str, Enum):
    """Resolution decisions recorded for AP exceptions."""
    APPROVED  = "APPROVED"    # Approved as-is or with minor acceptable variance
    EDITED    = "EDITED"      # Approved after manual correction to agreed terms
    REJECTED  = "REJECTED"    # Rejected outright (e.g. duplicate, invalid invoice)
    ESCALATED = "ESCALATED"   # Escalated to senior approver (CFO / Controller)


# ═════════════════════════════════════════════════════════════════════════════
# VENDOR & TRANSACTION MODELS
# ═════════════════════════════════════════════════════════════════════════════

class Vendor(BaseModel):
    """Fictional Indian enterprise supplier profile."""
    name: str = Field(description="Full legal business name (fictional)")
    slug: str = Field(description="URL/tag-safe lowercase slug")
    gstin: str = Field(description="15-character format-valid synthetic GSTIN")
    city: str = Field(description="Operating city in India")
    state: str = Field(description="Operating state")
    state_code: str = Field(description="2-digit GST state code")
    category: str = Field(description="Procurement spend category")
    standard_hsn: str = Field(description="Primary HSN/SAC code supplied")
    standard_gst_rate: Decimal = Field(description="Standard statutory GST rate (e.g. 0.18)")
    quirk_description: str = Field(description="Description of recurring operational quirk")
    dominant_action: ApproverDecision = Field(description="Standard approver outcome")


class PurchaseOrder(BaseModel):
    """Agreed contractual terms and valid procurement order."""
    po_number: str = Field(description="Unique Purchase Order number")
    vendor_name: str = Field(description="Supplier name")
    gstin: str = Field(description="Supplier GSTIN")
    issue_date: date = Field(description="Date PO was issued")
    valid_until: date = Field(description="Contractual validity end date")
    item_description: str = Field(description="Description of goods or services")
    hsn_code: str = Field(description="Agreed HSN / SAC code")
    unit_price_inr: Decimal = Field(description="Contracted unit rate in INR")
    quantity: int = Field(description="Ordered quantity")
    total_excl_tax_inr: Decimal = Field(description="Subtotal before taxes")
    gst_rate: Decimal = Field(description="Contracted GST rate (e.g. 0.18)")
    gst_amount_inr: Decimal = Field(description="Calculated GST in INR")
    total_inr: Decimal = Field(description="Total PO amount including tax")

    @field_validator("quantity")
    @classmethod
    def validate_positive_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"Quantity must be strictly positive, got {v}")
        return v

    @field_validator("unit_price_inr")
    @classmethod
    def validate_positive_unit_price(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0.0"):
            raise ValueError(f"Unit price must be strictly positive, got {v}")
        return v

    @field_validator("total_inr")
    @classmethod
    def validate_non_negative_total(cls, v: Decimal) -> Decimal:
        if v < Decimal("0.0"):
            raise ValueError(f"Total amount cannot be negative, got {v}")
        return v

    @classmethod
    def create(
        cls,
        po_number: str,
        vendor_name: str,
        gstin: str,
        issue_date: date,
        valid_until: date,
        item_description: str,
        hsn_code: str,
        unit_price_inr: Decimal,
        quantity: int,
        gst_rate: Decimal,
    ) -> "PurchaseOrder":
        subtotal = (unit_price_inr * Decimal(quantity)).quantize(Decimal("0.01"))
        tax = (subtotal * gst_rate).quantize(Decimal("0.01"))
        total = subtotal + tax
        return cls(
            po_number=po_number,
            vendor_name=vendor_name,
            gstin=gstin,
            issue_date=issue_date,
            valid_until=valid_until,
            item_description=item_description,
            hsn_code=hsn_code,
            unit_price_inr=unit_price_inr.quantize(Decimal("0.01")),
            quantity=quantity,
            total_excl_tax_inr=subtotal,
            gst_rate=gst_rate,
            gst_amount_inr=tax,
            total_inr=total,
        )


class GoodsReceiptNote(BaseModel):
    """Warehouse / logistics physical goods or services intake record."""
    grn_number: str = Field(description="Unique Goods Receipt Note reference")
    po_number: str = Field(description="Linked Purchase Order number")
    receipt_date: date = Field(description="Date items received at warehouse")
    received_quantity: int = Field(description="Total units physically delivered")
    accepted_quantity: int = Field(description="Units passing quality inspection")
    rejected_quantity: int = Field(default=0, description="Damaged or rejected units")
    inspection_notes: str = Field(default="Inspection cleared standard QA.")


class Invoice(BaseModel):
    """Supplier invoice submitted for payment."""
    invoice_number: str = Field(description="Supplier invoice number")
    vendor_name: str = Field(description="Supplier legal name")
    gstin: str = Field(description="Supplier GSTIN")
    invoice_date: date = Field(description="Date stated on invoice")
    po_number: str = Field(description="Referenced PO number")
    grn_number: Optional[str] = Field(default=None, description="Linked GRN reference if any")
    item_description: str = Field(description="Description of line items")
    hsn_code: str = Field(description="HSN / SAC code on invoice")
    unit_price_inr: Decimal = Field(description="Billed unit price in INR")
    quantity: int = Field(description="Billed quantity")
    total_excl_tax_inr: Decimal = Field(description="Billed subtotal before tax")
    gst_rate: Decimal = Field(description="Billed GST rate (e.g. 0.18, 0.12)")
    gst_amount_inr: Decimal = Field(description="Billed GST amount in INR")
    total_inr: Decimal = Field(description="Total payable amount in INR")

    @field_validator("quantity")
    @classmethod
    def validate_positive_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"Quantity must be strictly positive, got {v}")
        return v

    @field_validator("unit_price_inr")
    @classmethod
    def validate_positive_unit_price(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0.0"):
            raise ValueError(f"Unit price must be strictly positive, got {v}")
        return v

    @field_validator("total_inr")
    @classmethod
    def validate_non_negative_total(cls, v: Decimal) -> Decimal:
        if v < Decimal("0.0"):
            raise ValueError(f"Total amount cannot be negative, got {v}")
        return v

    @classmethod
    def create(
        cls,
        invoice_number: str,
        vendor_name: str,
        gstin: str,
        invoice_date: date,
        po_number: str,
        grn_number: Optional[str],
        item_description: str,
        hsn_code: str,
        unit_price_inr: Decimal,
        quantity: int,
        gst_rate: Decimal,
    ) -> "Invoice":
        subtotal = (unit_price_inr * Decimal(quantity)).quantize(Decimal("0.01"))
        tax = (subtotal * gst_rate).quantize(Decimal("0.01"))
        total = subtotal + tax
        return cls(
            invoice_number=invoice_number,
            vendor_name=vendor_name,
            gstin=gstin,
            invoice_date=invoice_date,
            po_number=po_number,
            grn_number=grn_number,
            item_description=item_description,
            hsn_code=hsn_code,
            unit_price_inr=unit_price_inr.quantize(Decimal("0.01")),
            quantity=quantity,
            total_excl_tax_inr=subtotal,
            gst_rate=gst_rate,
            gst_amount_inr=tax,
            total_inr=total,
        )


# ═════════════════════════════════════════════════════════════════════════════
# DISCREPANCY & THREE-WAY MATCHING RESULTS
# ═════════════════════════════════════════════════════════════════════════════

class Discrepancy(BaseModel):
    """Detailed itemization of an identified discrepancy."""
    exception_type: ExceptionType
    field: str = Field(description="Field that failed match (e.g. unit_price, quantity)")
    invoice_value: Any = Field(description="Value present on invoice")
    expected_value: Any = Field(description="Value expected from PO or GRN")
    delta_inr: Optional[Decimal] = Field(default=None, description="Financial discrepancy in INR if applicable")
    message: str = Field(description="Deterministic human explanation of discrepancy")


class MatchResult(BaseModel):
    """Structured output from deterministic 3-way matching."""
    is_match: bool = Field(description="True if invoice, PO, and GRN fully reconcile")
    exception_type: ExceptionType = Field(description="Primary exception type")
    primary_discrepancy: Optional[Discrepancy] = Field(default=None)
    all_discrepancies: list[Discrepancy] = Field(default_factory=list)
    invoice_number: str
    po_number: str
    vendor_name: str
    invoice_amount_inr: Decimal
    expected_amount_inr: Decimal
    explanation: str = Field(description="Summary explanation of match result")

    @property
    def discrepancies(self) -> list[Discrepancy]:
        """Convenience alias for all_discrepancies."""
        return self.all_discrepancies

    @property
    def summary(self) -> str:
        """Convenience alias for explanation."""
        return self.explanation

    @property
    def variance_inr(self) -> Decimal:
        """Financial discrepancy between invoice total and expected PO total."""
        return self.invoice_amount_inr - self.expected_amount_inr


# ═════════════════════════════════════════════════════════════════════════════
# HISTORICAL DECISION (SEEDED INTO MEMORY)
# ═════════════════════════════════════════════════════════════════════════════

class HistoricalDecision(BaseModel):
    """
    Historical exception resolution record to be retained in Hindsight memory.
    Represents past institutional learning: what happened + what human decided + reason.
    """
    invoice: Invoice
    po: PurchaseOrder
    grn: Optional[GoodsReceiptNote] = None
    match_result: MatchResult
    decision: ApproverDecision
    approver_role: ApproverRole
    human_reason: str
    outcome_inr: Decimal
    outcome_note: str
    timestamp: datetime  # Backdated event timestamp in UTC

    @computed_field
    def document_id(self) -> str:
        """Deterministic upsert identifier for Hindsight retain()."""
        return f"decision-{self.invoice.invoice_number}"

    @computed_field
    def tags(self) -> list[str]:
        """Scope-filterable tags for Hindsight recall()."""
        slug = self.invoice.vendor_name.lower().replace(" ", "-").replace(".", "")
        return [
            f"vendor:{slug}",
            f"exception:{self.match_result.exception_type.value.lower()}",
            f"decision:{self.decision.value.lower()}",
            f"gstin:{self.invoice.gstin}",
            f"approver:{self.approver_role.value.lower()}",
        ]

    def to_metadata(self) -> dict[str, str]:
        """
        String-only metadata mapping for Hindsight SDK (discovered in Milestone 1).
        All numeric values cast to formatted string representations.
        """
        return {
            "vendor_name": self.invoice.vendor_name,
            "gstin": self.invoice.gstin,
            "hsn_code": self.invoice.hsn_code,
            "po_number": self.po.po_number,
            "invoice_number": self.invoice.invoice_number,
            "amount_inr": f"{self.invoice.total_inr:.2f}",
            "exception_type": self.match_result.exception_type.value,
            "decision": self.decision.value,
            "approver_role": self.approver_role.value,
            "outcome_inr": f"{self.outcome_inr:.2f}",
        }

    def to_narrative(self) -> str:
        """
        Clean, factual narrative string retained in Hindsight.
        Per Plan v3 / Change #2: Contains ONLY what happened and what the human
        decided and why. Never includes vendor_quirk_summary or 'Tags:' lines.
        """
        dt_str = self.timestamp.strftime("%Y-%m-%d")
        inv = self.invoice
        po = self.po
        res = self.match_result

        narrative = (
            f"On {dt_str}, {inv.vendor_name} (GSTIN: {inv.gstin}) submitted invoice "
            f"{inv.invoice_number} against PO {po.po_number} for ₹{inv.total_inr:,.0f} "
            f"covering HSN {inv.hsn_code}.\n\n"
            f"The 3-way match failed because: {res.explanation}\n\n"
            f"Decision by {self.approver_role.value}: {self.decision.value}.\n"
            f"Reason: {self.human_reason}\n"
            f"Financial outcome: ₹{self.outcome_inr:,.0f} {self.outcome_note}."
        )
        return narrative


# ═════════════════════════════════════════════════════════════════════════════
# EVALUATION & HELD-OUT DATASET MODELS
# ═════════════════════════════════════════════════════════════════════════════

class ExpectedResolution(BaseModel):
    """
    Ground-truth human resolution label for evaluation.
    Kept separate from the future AI resolver input.
    """
    decision: ApproverDecision
    amount_inr: Decimal
    reason: str


class HeldOutInvoice(BaseModel):
    """
    Held-out invoice for benchmark evaluation and live queue simulation.
    NEVER retained into the memory bank.
    """
    invoice: Invoice
    po: PurchaseOrder
    grn: Optional[GoodsReceiptNote] = None
    match_result: MatchResult
    expected_resolution: ExpectedResolution = Field(
        description="Hidden ground truth label for benchmark scoring; never shown to AI resolver"
    )

