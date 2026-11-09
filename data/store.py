"""
data/store.py
────────────────────────────────────────────────────────────────────────────────
Persistent SQLite Storage for User Invoices, POs, GRNs, and Human Reviews.
Guarantees durability across Streamlit reruns, app restarts, and evaluations.
Uses string-based Decimal storage to completely avoid floating-point drift.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from agent.matcher import match_invoice
from data.models import (
    ApproverDecision,
    ApproverRole,
    Discrepancy,
    ExceptionType,
    GoodsReceiptNote,
    Invoice,
    MatchResult,
    PurchaseOrder,
    Vendor,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "ledgermind.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open connection with foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialize SQLite tables for persistent AP documents and review ledger."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vendors (
                name TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                gstin TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'General Procurement',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS purchase_orders (
                po_number TEXT PRIMARY KEY,
                vendor_name TEXT NOT NULL,
                gstin TEXT NOT NULL,
                issue_date TEXT NOT NULL,
                valid_until TEXT NOT NULL,
                item_description TEXT NOT NULL,
                hsn_code TEXT NOT NULL,
                unit_price_inr TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_excl_tax_inr TEXT NOT NULL,
                gst_rate TEXT NOT NULL,
                gst_amount_inr TEXT NOT NULL,
                total_inr TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS goods_receipts (
                grn_number TEXT PRIMARY KEY,
                po_number TEXT NOT NULL,
                receipt_date TEXT NOT NULL,
                received_quantity INTEGER NOT NULL,
                accepted_quantity INTEGER NOT NULL,
                rejected_quantity INTEGER NOT NULL DEFAULT 0,
                inspection_notes TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invoices (
                invoice_number TEXT PRIMARY KEY,
                vendor_name TEXT NOT NULL,
                gstin TEXT NOT NULL,
                invoice_date TEXT NOT NULL,
                po_number TEXT NOT NULL,
                grn_number TEXT,
                item_description TEXT NOT NULL,
                hsn_code TEXT NOT NULL,
                unit_price_inr TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_excl_tax_inr TEXT NOT NULL,
                gst_rate TEXT NOT NULL,
                gst_amount_inr TEXT NOT NULL,
                total_inr TEXT NOT NULL,
                is_user_created INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS human_reviews (
                invoice_number TEXT PRIMARY KEY,
                decision TEXT NOT NULL,
                approver_role TEXT NOT NULL,
                approved_amount_inr TEXT NOT NULL,
                rationale TEXT NOT NULL,
                hindsight_doc_id TEXT,
                hindsight_bank_id TEXT,
                hindsight_status TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            );
            """
        )


# ═════════════════════════════════════════════════════════════════════════════
# VENDORS
# ═════════════════════════════════════════════════════════════════════════════

def save_vendor(name: str, gstin: str, category: str = "General Procurement", db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    slug = name.lower().replace(" ", "-").replace(".", "")
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO vendors (name, slug, gstin, category, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                gstin=excluded.gstin,
                category=excluded.category
            """,
            (name, slug, gstin, category, now_iso),
        )


def list_vendors(db_path: Path = DB_PATH) -> List[Dict[str, str]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM vendors ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDERS
# ═════════════════════════════════════════════════════════════════════════════

def save_purchase_order(po: PurchaseOrder, db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO purchase_orders (
                po_number, vendor_name, gstin, issue_date, valid_until,
                item_description, hsn_code, unit_price_inr, quantity,
                total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(po_number) DO UPDATE SET
                vendor_name=excluded.vendor_name,
                gstin=excluded.gstin,
                issue_date=excluded.issue_date,
                valid_until=excluded.valid_until,
                item_description=excluded.item_description,
                hsn_code=excluded.hsn_code,
                unit_price_inr=excluded.unit_price_inr,
                quantity=excluded.quantity,
                total_excl_tax_inr=excluded.total_excl_tax_inr,
                gst_rate=excluded.gst_rate,
                gst_amount_inr=excluded.gst_amount_inr,
                total_inr=excluded.total_inr
            """,
            (
                po.po_number,
                po.vendor_name,
                po.gstin,
                po.issue_date.isoformat(),
                po.valid_until.isoformat(),
                po.item_description,
                po.hsn_code,
                str(po.unit_price_inr),
                po.quantity,
                str(po.total_excl_tax_inr),
                str(po.gst_rate),
                str(po.gst_amount_inr),
                str(po.total_inr),
                now_iso,
            ),
        )


def get_purchase_order(po_number: str, db_path: Path = DB_PATH) -> Optional[PurchaseOrder]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        r = conn.execute("SELECT * FROM purchase_orders WHERE po_number = ?", (po_number,)).fetchone()
        if not r:
            return None
        return PurchaseOrder(
            po_number=r["po_number"],
            vendor_name=r["vendor_name"],
            gstin=r["gstin"],
            issue_date=date.fromisoformat(r["issue_date"]),
            valid_until=date.fromisoformat(r["valid_until"]),
            item_description=r["item_description"],
            hsn_code=r["hsn_code"],
            unit_price_inr=Decimal(r["unit_price_inr"]),
            quantity=r["quantity"],
            total_excl_tax_inr=Decimal(r["total_excl_tax_inr"]),
            gst_rate=Decimal(r["gst_rate"]),
            gst_amount_inr=Decimal(r["gst_amount_inr"]),
            total_inr=Decimal(r["total_inr"]),
        )


def list_purchase_orders(db_path: Path = DB_PATH) -> List[PurchaseOrder]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM purchase_orders ORDER BY issue_date DESC").fetchall()
        pos = []
        for r in rows:
            pos.append(
                PurchaseOrder(
                    po_number=r["po_number"],
                    vendor_name=r["vendor_name"],
                    gstin=r["gstin"],
                    issue_date=date.fromisoformat(r["issue_date"]),
                    valid_until=date.fromisoformat(r["valid_until"]),
                    item_description=r["item_description"],
                    hsn_code=r["hsn_code"],
                    unit_price_inr=Decimal(r["unit_price_inr"]),
                    quantity=r["quantity"],
                    total_excl_tax_inr=Decimal(r["total_excl_tax_inr"]),
                    gst_rate=Decimal(r["gst_rate"]),
                    gst_amount_inr=Decimal(r["gst_amount_inr"]),
                    total_inr=Decimal(r["total_inr"]),
                )
            )
        return pos


# ═════════════════════════════════════════════════════════════════════════════
# GOODS RECEIPTS
# ═════════════════════════════════════════════════════════════════════════════

def save_goods_receipt(grn: GoodsReceiptNote, db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO goods_receipts (
                grn_number, po_number, receipt_date, received_quantity,
                accepted_quantity, rejected_quantity, inspection_notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(grn_number) DO UPDATE SET
                po_number=excluded.po_number,
                receipt_date=excluded.receipt_date,
                received_quantity=excluded.received_quantity,
                accepted_quantity=excluded.accepted_quantity,
                rejected_quantity=excluded.rejected_quantity,
                inspection_notes=excluded.inspection_notes
            """,
            (
                grn.grn_number,
                grn.po_number,
                grn.receipt_date.isoformat(),
                grn.received_quantity,
                grn.accepted_quantity,
                grn.rejected_quantity,
                grn.inspection_notes,
                now_iso,
            ),
        )


def get_goods_receipt(grn_number: str, db_path: Path = DB_PATH) -> Optional[GoodsReceiptNote]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        r = conn.execute("SELECT * FROM goods_receipts WHERE grn_number = ?", (grn_number,)).fetchone()
        if not r:
            return None
        return GoodsReceiptNote(
            grn_number=r["grn_number"],
            po_number=r["po_number"],
            receipt_date=date.fromisoformat(r["receipt_date"]),
            received_quantity=r["received_quantity"],
            accepted_quantity=r["accepted_quantity"],
            rejected_quantity=r["rejected_quantity"],
            inspection_notes=r["inspection_notes"],
        )


def get_goods_receipt_by_po(po_number: str, db_path: Path = DB_PATH) -> Optional[GoodsReceiptNote]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        r = conn.execute("SELECT * FROM goods_receipts WHERE po_number = ? ORDER BY receipt_date DESC LIMIT 1", (po_number,)).fetchone()
        if not r:
            return None
        return GoodsReceiptNote(
            grn_number=r["grn_number"],
            po_number=r["po_number"],
            receipt_date=date.fromisoformat(r["receipt_date"]),
            received_quantity=r["received_quantity"],
            accepted_quantity=r["accepted_quantity"],
            rejected_quantity=r["rejected_quantity"],
            inspection_notes=r["inspection_notes"],
        )


def list_goods_receipts(db_path: Path = DB_PATH) -> List[GoodsReceiptNote]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM goods_receipts ORDER BY receipt_date DESC").fetchall()
        grns = []
        for r in rows:
            grns.append(
                GoodsReceiptNote(
                    grn_number=r["grn_number"],
                    po_number=r["po_number"],
                    receipt_date=date.fromisoformat(r["receipt_date"]),
                    received_quantity=r["received_quantity"],
                    accepted_quantity=r["accepted_quantity"],
                    rejected_quantity=r["rejected_quantity"],
                    inspection_notes=r["inspection_notes"],
                )
            )
        return grns


# ═════════════════════════════════════════════════════════════════════════════
# INVOICES & USER INVOICE RECORDS
# ═════════════════════════════════════════════════════════════════════════════

def save_invoice(inv: Invoice, is_user_created: bool = True, db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO invoices (
                invoice_number, vendor_name, gstin, invoice_date, po_number, grn_number,
                item_description, hsn_code, unit_price_inr, quantity,
                total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr, is_user_created, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(invoice_number) DO UPDATE SET
                vendor_name=excluded.vendor_name,
                gstin=excluded.gstin,
                invoice_date=excluded.invoice_date,
                po_number=excluded.po_number,
                grn_number=excluded.grn_number,
                item_description=excluded.item_description,
                hsn_code=excluded.hsn_code,
                unit_price_inr=excluded.unit_price_inr,
                quantity=excluded.quantity,
                total_excl_tax_inr=excluded.total_excl_tax_inr,
                gst_rate=excluded.gst_rate,
                gst_amount_inr=excluded.gst_amount_inr,
                total_inr=excluded.total_inr
            """,
            (
                inv.invoice_number,
                inv.vendor_name,
                inv.gstin,
                inv.invoice_date.isoformat(),
                inv.po_number,
                inv.grn_number,
                inv.item_description,
                inv.hsn_code,
                str(inv.unit_price_inr),
                inv.quantity,
                str(inv.total_excl_tax_inr),
                str(inv.gst_rate),
                str(inv.gst_amount_inr),
                str(inv.total_inr),
                1 if is_user_created else 0,
                now_iso,
            ),
        )


def _row_to_invoice(r: sqlite3.Row) -> Invoice:
    return Invoice(
        invoice_number=r["invoice_number"],
        vendor_name=r["vendor_name"],
        gstin=r["gstin"],
        invoice_date=date.fromisoformat(r["invoice_date"]),
        po_number=r["po_number"],
        grn_number=r["grn_number"],
        item_description=r["item_description"],
        hsn_code=r["hsn_code"],
        unit_price_inr=Decimal(r["unit_price_inr"]),
        quantity=r["quantity"],
        total_excl_tax_inr=Decimal(r["total_excl_tax_inr"]),
        gst_rate=Decimal(r["gst_rate"]),
        gst_amount_inr=Decimal(r["gst_amount_inr"]),
        total_inr=Decimal(r["total_inr"]),
    )


class UserInvoiceBundle:
    """Represents a fully reconciled user invoice linked with PO, GRN, and match result."""
    def __init__(
        self,
        invoice: Invoice,
        po: Optional[PurchaseOrder],
        grn: Optional[GoodsReceiptNote],
        match_result: MatchResult,
        is_user_created: bool = True,
    ):
        self.invoice = invoice
        self.po = po
        self.grn = grn
        self.match_result = match_result
        self.is_user_created = is_user_created
        self.expected_resolution = None


def get_user_invoices_reconciled(db_path: Path = DB_PATH) -> List[UserInvoiceBundle]:
    """Retrieve all user-created invoices from SQLite and compute deterministic 3-way match."""
    init_db(db_path)
    bundles: List[UserInvoiceBundle] = []

    with get_connection(db_path) as conn:
        inv_rows = conn.execute("SELECT * FROM invoices ORDER BY invoice_date DESC, created_at DESC").fetchall()
        for r in inv_rows:
            inv = _row_to_invoice(r)
            po = get_purchase_order(inv.po_number, db_path=db_path)
            grn = None
            if inv.grn_number:
                grn = get_goods_receipt(inv.grn_number, db_path=db_path)
            if not grn:
                grn = get_goods_receipt_by_po(inv.po_number, db_path=db_path)

            if po:
                match_res = match_invoice(invoice=inv, po=po, grn=grn)
            else:
                # Pending documents state: PO missing
                match_res = MatchResult(
                    is_match=False,
                    exception_type=ExceptionType.NONE,
                    invoice_number=inv.invoice_number,
                    po_number=inv.po_number,
                    vendor_name=inv.vendor_name,
                    invoice_amount_inr=inv.total_inr,
                    expected_amount_inr=Decimal("0.00"),
                    explanation=f"Pending PO documentation: Purchase order '{inv.po_number}' is not yet in repository.",
                    all_discrepancies=[
                        Discrepancy(
                            exception_type=ExceptionType.NONE,
                            field="po_number",
                            invoice_value=inv.po_number,
                            expected_value="Valid PO in repository",
                            message=f"Purchase order '{inv.po_number}' was not found.",
                        )
                    ],
                )

            bundles.append(
                UserInvoiceBundle(
                    invoice=inv,
                    po=po,
                    grn=grn,
                    match_result=match_res,
                    is_user_created=bool(r["is_user_created"]),
                )
            )

    return bundles


# ═════════════════════════════════════════════════════════════════════════════
# HUMAN REVIEW PERSISTENCE
# ═════════════════════════════════════════════════════════════════════════════

def save_human_review(
    invoice_number: str,
    decision: str,
    approver_role: str,
    approved_amount_inr: Decimal,
    rationale: str,
    hindsight_doc_id: Optional[str] = None,
    hindsight_bank_id: Optional[str] = None,
    hindsight_status: str = "PENDING_SYNC",
    reviewed_at: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> None:
    init_db(db_path)
    now_iso = reviewed_at or datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO human_reviews (
                invoice_number, decision, approver_role, approved_amount_inr,
                rationale, hindsight_doc_id, hindsight_bank_id, hindsight_status, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(invoice_number) DO UPDATE SET
                decision=excluded.decision,
                approver_role=excluded.approver_role,
                approved_amount_inr=excluded.approved_amount_inr,
                rationale=excluded.rationale,
                hindsight_doc_id=excluded.hindsight_doc_id,
                hindsight_bank_id=excluded.hindsight_bank_id,
                hindsight_status=excluded.hindsight_status,
                reviewed_at=excluded.reviewed_at
            """,
            (
                invoice_number,
                decision,
                approver_role,
                str(approved_amount_inr),
                rationale,
                hindsight_doc_id,
                hindsight_bank_id,
                hindsight_status,
                now_iso,
            ),
        )


def get_all_human_reviews(db_path: Path = DB_PATH) -> Dict[str, Dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM human_reviews").fetchall()
        reviews = {}
        for r in rows:
            reviews[r["invoice_number"]] = {
                "decision": r["decision"],
                "role": r["approver_role"],
                "amount": Decimal(r["approved_amount_inr"]),
                "reason": r["rationale"],
                "timestamp": r["reviewed_at"],
                "document_id": r["hindsight_doc_id"],
                "bank_id": r["hindsight_bank_id"],
                "hindsight_status": r["hindsight_status"],
            }
        return reviews


def get_human_review(invoice_number: str, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    reviews = get_all_human_reviews(db_path=db_path)
    return reviews.get(invoice_number)

