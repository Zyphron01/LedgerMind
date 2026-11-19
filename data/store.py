"""
data/store.py
────────────────────────────────────────────────────────────────────────────────
Persistent SQLite Storage for User Invoices, POs, GRNs, and Human Reviews.
Single source of truth for all operational AP records (benchmark + user).
Enforces relational integrity via foreign keys, cascading updates, indexes,
and atomic bundle transactions with string-based Decimal storage.
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
    ExpectedResolution,
    GoodsReceiptNote,
    Invoice,
    MatchResult,
    PurchaseOrder,
    Vendor,
)
from data.vendors import ALL_VENDORS

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "ledgermind.db"
HELD_OUT_FILE = ROOT_DIR / "data" / "held_out_invoices.json"
EVAL_LABELS_FILE = ROOT_DIR / "data" / "held_out_evaluation_labels.json"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_milestone3(conn: sqlite3.Connection) -> None:
    """
    Milestone 3 Migration:
      1. Protect human review history by changing human_reviews FK from ON DELETE CASCADE to ON DELETE RESTRICT.
      2. Introduce review_audit_log table to preserve historical review versions on supersede.
      3. Add is_archived and is_incomplete columns to invoices table.
      4. Ensure indexes and run PRAGMA foreign_key_check.
    Idempotent and safe on repeated executions.
    """
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "invoices" not in tables:
        return

    # 1. Check and add columns to invoices
    inv_cols = [r["name"] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()]
    with conn:
        if "is_archived" not in inv_cols:
            conn.execute("ALTER TABLE invoices ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
        if "is_incomplete" not in inv_cols:
            conn.execute("ALTER TABLE invoices ADD COLUMN is_incomplete INTEGER NOT NULL DEFAULT 0")

    # 2. Check human_reviews FK constraint action
    if "human_reviews" in tables:
        hr_ddl_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='human_reviews'").fetchone()
        if hr_ddl_row and "ON DELETE CASCADE" in hr_ddl_row[0].upper():
            conn.execute("PRAGMA foreign_keys = OFF;")
            with conn:
                conn.execute("""
                    CREATE TABLE human_reviews_m3 (
                        invoice_number TEXT PRIMARY KEY,
                        decision TEXT NOT NULL,
                        approver_role TEXT NOT NULL,
                        approved_amount_inr TEXT NOT NULL,
                        rationale TEXT NOT NULL,
                        hindsight_doc_id TEXT,
                        hindsight_bank_id TEXT,
                        hindsight_status TEXT NOT NULL,
                        reviewed_at TEXT NOT NULL,
                        FOREIGN KEY (invoice_number) REFERENCES invoices(invoice_number) ON UPDATE CASCADE ON DELETE RESTRICT
                    );
                """)
                conn.execute("""
                    INSERT INTO human_reviews_m3 (
                        invoice_number, decision, approver_role, approved_amount_inr,
                        rationale, hindsight_doc_id, hindsight_bank_id, hindsight_status, reviewed_at
                    )
                    SELECT
                        invoice_number, decision, approver_role, approved_amount_inr,
                        rationale, hindsight_doc_id, hindsight_bank_id, hindsight_status, reviewed_at
                    FROM human_reviews;
                """)
                conn.execute("DROP TABLE human_reviews;")
                conn.execute("ALTER TABLE human_reviews_m3 RENAME TO human_reviews;")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_human_reviews_invoice ON human_reviews(invoice_number);")
            conn.execute("PRAGMA foreign_keys = ON;")
            fk_errs = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errs:
                raise RuntimeError(f"Foreign key check failed after Milestone 3 migration: {fk_errs}")

    # 3. Create review_audit_log table if not exists
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT NOT NULL,
                version INTEGER NOT NULL,
                decision TEXT NOT NULL,
                approver_role TEXT NOT NULL,
                approved_amount_inr TEXT NOT NULL,
                rationale TEXT NOT NULL,
                hindsight_doc_id TEXT,
                hindsight_bank_id TEXT,
                hindsight_status TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                superseded_at TEXT NOT NULL,
                FOREIGN KEY (invoice_number) REFERENCES invoices(invoice_number) ON UPDATE CASCADE ON DELETE RESTRICT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_audit_log_inv ON review_audit_log(invoice_number);")


def init_db(db_path: Path = DB_PATH) -> None:
    """
    Initialize SQLite schema with relational integrity and idempotent migrations.
    Safely upgrades legacy schemas to enforce foreign keys and seeds benchmark records.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    needs_migration = False

    if "invoices" in tables:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(invoices)").fetchall()]
        if "raw_po_number" not in cols or "is_benchmark" not in cols:
            needs_migration = True
        else:
            ddl_row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'").fetchone()
            if ddl_row and "FOREIGN KEY" not in ddl_row[0]:
                needs_migration = True

    if needs_migration:
        conn.execute("PRAGMA foreign_keys = OFF;")
        with conn:
            conn.execute("""
                CREATE TABLE vendors_new (
                    name TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    gstin TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'General Procurement',
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE purchase_orders_new (
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
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (vendor_name) REFERENCES vendors_new(name) ON UPDATE CASCADE
                );
            """)

            conn.execute("""
                CREATE TABLE goods_receipts_new (
                    grn_number TEXT PRIMARY KEY,
                    po_number TEXT NOT NULL,
                    receipt_date TEXT NOT NULL,
                    received_quantity INTEGER NOT NULL,
                    accepted_quantity INTEGER NOT NULL,
                    rejected_quantity INTEGER NOT NULL DEFAULT 0,
                    inspection_notes TEXT NOT NULL,
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (po_number) REFERENCES purchase_orders_new(po_number) ON UPDATE CASCADE
                );
            """)

            conn.execute("""
                CREATE TABLE invoices_new (
                    invoice_number TEXT PRIMARY KEY,
                    vendor_name TEXT NOT NULL,
                    gstin TEXT NOT NULL,
                    invoice_date TEXT NOT NULL,
                    po_number TEXT,
                    raw_po_number TEXT NOT NULL,
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
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (vendor_name) REFERENCES vendors_new(name) ON UPDATE CASCADE,
                    FOREIGN KEY (po_number) REFERENCES purchase_orders_new(po_number) ON UPDATE CASCADE ON DELETE SET NULL,
                    FOREIGN KEY (grn_number) REFERENCES goods_receipts_new(grn_number) ON UPDATE CASCADE ON DELETE SET NULL
                );
            """)

            conn.execute("""
                CREATE TABLE human_reviews_new (
                    invoice_number TEXT PRIMARY KEY,
                    decision TEXT NOT NULL,
                    approver_role TEXT NOT NULL,
                    approved_amount_inr TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    hindsight_doc_id TEXT,
                    hindsight_bank_id TEXT,
                    hindsight_status TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    FOREIGN KEY (invoice_number) REFERENCES invoices_new(invoice_number) ON UPDATE CASCADE ON DELETE CASCADE
                );
            """)

            conn.execute("""
                INSERT INTO vendors_new (name, slug, gstin, category, is_benchmark, created_at)
                SELECT name, slug, gstin, category, 0, created_at FROM vendors;
            """)

            conn.execute("""
                INSERT INTO purchase_orders_new (
                    po_number, vendor_name, gstin, issue_date, valid_until,
                    item_description, hsn_code, unit_price_inr, quantity,
                    total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr,
                    is_benchmark, created_at
                )
                SELECT
                    po_number, vendor_name, gstin, issue_date, valid_until,
                    item_description, hsn_code, unit_price_inr, quantity,
                    total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr,
                    0, created_at
                FROM purchase_orders;
            """)

            conn.execute("""
                INSERT INTO goods_receipts_new (
                    grn_number, po_number, receipt_date, received_quantity,
                    accepted_quantity, rejected_quantity, inspection_notes,
                    is_benchmark, created_at
                )
                SELECT
                    grn_number, po_number, receipt_date, received_quantity,
                    accepted_quantity, rejected_quantity, inspection_notes,
                    0, created_at
                FROM goods_receipts;
            """)

            conn.execute("""
                INSERT INTO invoices_new (
                    invoice_number, vendor_name, gstin, invoice_date, po_number, raw_po_number, grn_number,
                    item_description, hsn_code, unit_price_inr, quantity,
                    total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr,
                    is_user_created, is_benchmark, created_at
                )
                SELECT
                    invoice_number, vendor_name, gstin, invoice_date, po_number, po_number, grn_number,
                    item_description, hsn_code, unit_price_inr, quantity,
                    total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr,
                    is_user_created, 0, created_at
                FROM invoices;
            """)

            conn.execute("""
                INSERT INTO human_reviews_new (
                    invoice_number, decision, approver_role, approved_amount_inr,
                    rationale, hindsight_doc_id, hindsight_bank_id, hindsight_status, reviewed_at
                )
                SELECT
                    invoice_number, decision, approver_role, approved_amount_inr,
                    rationale, hindsight_doc_id, hindsight_bank_id, hindsight_status, reviewed_at
                FROM human_reviews;
            """)

            conn.execute("DROP TABLE human_reviews;")
            conn.execute("DROP TABLE invoices;")
            conn.execute("DROP TABLE goods_receipts;")
            conn.execute("DROP TABLE purchase_orders;")
            conn.execute("DROP TABLE vendors;")

            conn.execute("ALTER TABLE vendors_new RENAME TO vendors;")
            conn.execute("ALTER TABLE purchase_orders_new RENAME TO purchase_orders;")
            conn.execute("ALTER TABLE goods_receipts_new RENAME TO goods_receipts;")
            conn.execute("ALTER TABLE invoices_new RENAME TO invoices;")
            conn.execute("ALTER TABLE human_reviews_new RENAME TO human_reviews;")

        conn.execute("PRAGMA foreign_keys = ON;")

    else:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS vendors (
                    name TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    gstin TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'General Procurement',
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
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
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (vendor_name) REFERENCES vendors(name) ON UPDATE CASCADE
                );

                CREATE TABLE IF NOT EXISTS goods_receipts (
                    grn_number TEXT PRIMARY KEY,
                    po_number TEXT NOT NULL,
                    receipt_date TEXT NOT NULL,
                    received_quantity INTEGER NOT NULL,
                    accepted_quantity INTEGER NOT NULL,
                    rejected_quantity INTEGER NOT NULL DEFAULT 0,
                    inspection_notes TEXT NOT NULL,
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (po_number) REFERENCES purchase_orders(po_number) ON UPDATE CASCADE
                );

                CREATE TABLE IF NOT EXISTS invoices (
                    invoice_number TEXT PRIMARY KEY,
                    vendor_name TEXT NOT NULL,
                    gstin TEXT NOT NULL,
                    invoice_date TEXT NOT NULL,
                    po_number TEXT,
                    raw_po_number TEXT NOT NULL,
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
                    is_benchmark INTEGER NOT NULL DEFAULT 0,
                    is_incomplete INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (vendor_name) REFERENCES vendors(name) ON UPDATE CASCADE,
                    FOREIGN KEY (po_number) REFERENCES purchase_orders(po_number) ON UPDATE CASCADE ON DELETE SET NULL,
                    FOREIGN KEY (grn_number) REFERENCES goods_receipts(grn_number) ON UPDATE CASCADE ON DELETE SET NULL
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
                    reviewed_at TEXT NOT NULL,
                    FOREIGN KEY (invoice_number) REFERENCES invoices(invoice_number) ON UPDATE CASCADE ON DELETE RESTRICT
                );
            """)

    # Always ensure indexes exist
    with conn:
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices(vendor_name);
            CREATE INDEX IF NOT EXISTS idx_invoices_po ON invoices(po_number);
            CREATE INDEX IF NOT EXISTS idx_invoices_raw_po ON invoices(raw_po_number);
            CREATE INDEX IF NOT EXISTS idx_invoices_grn ON invoices(grn_number);
            CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
            CREATE INDEX IF NOT EXISTS idx_purchase_orders_vendor ON purchase_orders(vendor_name);
            CREATE INDEX IF NOT EXISTS idx_goods_receipts_po ON goods_receipts(po_number);
            CREATE INDEX IF NOT EXISTS idx_human_reviews_invoice ON human_reviews(invoice_number);
        """)

    # Always execute idempotent Milestone 3 schema hardening
    _migrate_milestone3(conn)

    # Seed benchmark dataset if not already present in SQLite
    bench_cnt = conn.execute("SELECT count(*) FROM invoices WHERE is_benchmark = 1").fetchone()[0]
    if bench_cnt < 20 and HELD_OUT_FILE.exists():
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn:
            for v in ALL_VENDORS:
                conn.execute("""
                    INSERT INTO vendors (name, slug, gstin, category, is_benchmark, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(name) DO UPDATE SET is_benchmark=1;
                """, (v.name, v.slug, v.gstin, v.category, now_iso))

            with open(HELD_OUT_FILE, "r", encoding="utf-8") as f:
                sample_invs = json.load(f)

            for item in sample_invs:
                inv = item["invoice"]
                po = item.get("po")
                grn = item.get("grn")

                if po:
                    conn.execute("""
                        INSERT INTO purchase_orders (
                            po_number, vendor_name, gstin, issue_date, valid_until,
                            item_description, hsn_code, unit_price_inr, quantity,
                            total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr,
                            is_benchmark, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        ON CONFLICT(po_number) DO UPDATE SET is_benchmark=1;
                    """, (
                        po["po_number"], po["vendor_name"], po["gstin"],
                        po["issue_date"], po["valid_until"], po["item_description"],
                        po["hsn_code"], str(po["unit_price_inr"]), po["quantity"],
                        str(po["total_excl_tax_inr"]), str(po["gst_rate"]),
                        str(po["gst_amount_inr"]), str(po["total_inr"]), now_iso
                    ))

                if grn:
                    conn.execute("""
                        INSERT INTO goods_receipts (
                            grn_number, po_number, receipt_date, received_quantity,
                            accepted_quantity, rejected_quantity, inspection_notes,
                            is_benchmark, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                        ON CONFLICT(grn_number) DO UPDATE SET is_benchmark=1;
                    """, (
                        grn["grn_number"], grn["po_number"], grn["receipt_date"],
                        grn["received_quantity"], grn["accepted_quantity"],
                        grn.get("rejected_quantity", 0), grn.get("inspection_notes", ""), now_iso
                    ))

                conn.execute("""
                    INSERT INTO invoices (
                        invoice_number, vendor_name, gstin, invoice_date, po_number, raw_po_number, grn_number,
                        item_description, hsn_code, unit_price_inr, quantity,
                        total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr,
                        is_user_created, is_benchmark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
                    ON CONFLICT(invoice_number) DO UPDATE SET is_benchmark=1;
                """, (
                    inv["invoice_number"], inv["vendor_name"], inv["gstin"],
                    inv["invoice_date"], inv.get("po_number"), inv.get("po_number", ""),
                    inv.get("grn_number"), inv["item_description"], inv["hsn_code"],
                    str(inv["unit_price_inr"]), inv["quantity"], str(inv["total_excl_tax_inr"]),
                    str(inv["gst_rate"]), str(inv["gst_amount_inr"]), str(inv["total_inr"]), now_iso
                ))

    conn.close()


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


def list_all_vendor_names(db_path: Path = DB_PATH) -> List[str]:
    """Retrieve all unique vendor names from SQLite sorted alphabetically."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT name FROM vendors ORDER BY name ASC").fetchall()
        return [r["name"] for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# PURCHASE ORDERS
# ═════════════════════════════════════════════════════════════════════════════

def save_purchase_order(po: PurchaseOrder, db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        # Auto-ensure vendor exists to preserve foreign key integrity
        slug = po.vendor_name.lower().replace(" ", "-").replace(".", "")
        conn.execute(
            """
            INSERT INTO vendors (name, slug, gstin, category, created_at)
            VALUES (?, ?, ?, 'General Procurement', ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (po.vendor_name, slug, po.gstin, now_iso),
        )

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

        # Auto-link any waiting invoices that reference this PO
        conn.execute(
            """
            UPDATE invoices
            SET po_number = ?, is_incomplete = 0
            WHERE raw_po_number = ? AND (po_number IS NULL OR po_number = '')
            """,
            (po.po_number, po.po_number),
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

        # Auto-link GRN to any invoice sharing this po_number that lacks a GRN
        conn.execute(
            """
            UPDATE invoices
            SET grn_number = ?
            WHERE po_number = ? AND (grn_number IS NULL OR grn_number = '')
            """,
            (grn.grn_number, grn.po_number),
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
        r = conn.execute(
            "SELECT * FROM goods_receipts WHERE po_number = ? ORDER BY receipt_date DESC LIMIT 1",
            (po_number,),
        ).fetchone()
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
# INVOICES & ATOMIC BUNDLE PERSISTENCE
# ═════════════════════════════════════════════════════════════════════════════

def save_invoice(inv: Invoice, is_user_created: bool = True, db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        # Auto-ensure vendor exists
        slug = inv.vendor_name.lower().replace(" ", "-").replace(".", "")
        conn.execute(
            """
            INSERT INTO vendors (name, slug, gstin, category, created_at)
            VALUES (?, ?, ?, 'General Procurement', ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (inv.vendor_name, slug, inv.gstin, now_iso),
        )

        # Check if PO exists to enforce FK or set NULL while storing raw_po_number
        po_exists = None
        if inv.po_number:
            po_exists = conn.execute("SELECT 1 FROM purchase_orders WHERE po_number = ?", (inv.po_number,)).fetchone()
        resolved_po = inv.po_number if po_exists else None
        is_incomplete = 1 if resolved_po is None else 0

        # Check if GRN exists
        grn_exists = None
        if inv.grn_number:
            grn_exists = conn.execute("SELECT 1 FROM goods_receipts WHERE grn_number = ?", (inv.grn_number,)).fetchone()
        resolved_grn = inv.grn_number if grn_exists else None

        conn.execute(
            """
            INSERT INTO invoices (
                invoice_number, vendor_name, gstin, invoice_date, po_number, raw_po_number, grn_number,
                item_description, hsn_code, unit_price_inr, quantity,
                total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr, is_user_created,
                is_incomplete, is_archived, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(invoice_number) DO UPDATE SET
                vendor_name=excluded.vendor_name,
                gstin=excluded.gstin,
                invoice_date=excluded.invoice_date,
                po_number=excluded.po_number,
                raw_po_number=excluded.raw_po_number,
                grn_number=excluded.grn_number,
                item_description=excluded.item_description,
                hsn_code=excluded.hsn_code,
                unit_price_inr=excluded.unit_price_inr,
                quantity=excluded.quantity,
                total_excl_tax_inr=excluded.total_excl_tax_inr,
                gst_rate=excluded.gst_rate,
                gst_amount_inr=excluded.gst_amount_inr,
                total_inr=excluded.total_inr,
                is_incomplete=excluded.is_incomplete
            """,
            (
                inv.invoice_number,
                inv.vendor_name,
                inv.gstin,
                inv.invoice_date.isoformat(),
                resolved_po,
                inv.po_number or "",
                resolved_grn,
                inv.item_description,
                inv.hsn_code,
                str(inv.unit_price_inr),
                inv.quantity,
                str(inv.total_excl_tax_inr),
                str(inv.gst_rate),
                str(inv.gst_amount_inr),
                str(inv.total_inr),
                1 if is_user_created else 0,
                is_incomplete,
                now_iso,
            ),
        )


def save_document_bundle(
    vendor: Optional[Dict[str, str]],
    po: Optional[PurchaseOrder],
    grn: Optional[GoodsReceiptNote],
    invoice: Invoice,
    is_user_created: bool = True,
    db_path: Path = DB_PATH,
) -> None:
    """
    Save an entire AP document bundle in one atomic SQLite transaction.
    If any single insertion fails, all modifications roll back completely.
    """
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        with conn:
            # 1. Vendor
            v_name = (vendor.get("name") if vendor else None) or (po.vendor_name if po else invoice.vendor_name)
            v_gstin = (vendor.get("gstin") if vendor else None) or (po.gstin if po else invoice.gstin)
            v_cat = (vendor.get("category") if vendor else None) or "General Procurement"
            v_slug = v_name.lower().replace(" ", "-").replace(".", "")
            conn.execute(
                """
                INSERT INTO vendors (name, slug, gstin, category, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    gstin=excluded.gstin,
                    category=excluded.category
                """,
                (v_name, v_slug, v_gstin, v_cat, now_iso),
            )

            # 2. Purchase Order
            if po:
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

            # 3. Goods Receipt
            if grn:
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

            # 4. Invoice
            po_num_to_link = po.po_number if po else None
            grn_num_to_link = grn.grn_number if grn else None
            raw_po = invoice.po_number or (po.po_number if po else "")
            is_incomplete = 1 if po_num_to_link is None else 0

            conn.execute(
                """
                INSERT INTO invoices (
                    invoice_number, vendor_name, gstin, invoice_date, po_number, raw_po_number, grn_number,
                    item_description, hsn_code, unit_price_inr, quantity,
                    total_excl_tax_inr, gst_rate, gst_amount_inr, total_inr, is_user_created,
                    is_incomplete, is_archived, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(invoice_number) DO UPDATE SET
                    vendor_name=excluded.vendor_name,
                    gstin=excluded.gstin,
                    invoice_date=excluded.invoice_date,
                    po_number=excluded.po_number,
                    raw_po_number=excluded.raw_po_number,
                    grn_number=excluded.grn_number,
                    item_description=excluded.item_description,
                    hsn_code=excluded.hsn_code,
                    unit_price_inr=excluded.unit_price_inr,
                    quantity=excluded.quantity,
                    total_excl_tax_inr=excluded.total_excl_tax_inr,
                    gst_rate=excluded.gst_rate,
                    gst_amount_inr=excluded.gst_amount_inr,
                    total_inr=excluded.total_inr,
                    is_incomplete=excluded.is_incomplete
                """,
                (
                    invoice.invoice_number,
                    invoice.vendor_name,
                    invoice.gstin,
                    invoice.invoice_date.isoformat(),
                    po_num_to_link,
                    raw_po,
                    grn_num_to_link,
                    invoice.item_description,
                    invoice.hsn_code,
                    str(invoice.unit_price_inr),
                    invoice.quantity,
                    str(invoice.total_excl_tax_inr),
                    str(invoice.gst_rate),
                    str(invoice.gst_amount_inr),
                    str(invoice.total_inr),
                    1 if is_user_created else 0,
                    is_incomplete,
                    now_iso,
                ),
            )


# ═════════════════════════════════════════════════════════════════════════════
# UNIFIED RECONCILED BUNDLE REPOSITORY
# ═════════════════════════════════════════════════════════════════════════════

class UserInvoiceBundle:
    """Represents a fully reconciled invoice linked with PO, GRN, match result, and optional expected resolution."""
    def __init__(
        self,
        invoice: Invoice,
        po: Optional[PurchaseOrder],
        grn: Optional[GoodsReceiptNote],
        match_result: MatchResult,
        is_user_created: bool = True,
        expected_resolution: Optional[Any] = None,
        is_incomplete: bool = False,
        is_archived: bool = False,
    ):
        self.invoice = invoice
        self.po = po
        self.grn = grn
        self.match_result = match_result
        self.is_user_created = is_user_created
        self.expected_resolution = expected_resolution
        self.is_incomplete = is_incomplete
        self.is_archived = is_archived


ReconciledInvoiceBundle = UserInvoiceBundle


def _row_to_invoice(r: sqlite3.Row) -> Invoice:
    return Invoice(
        invoice_number=r["invoice_number"],
        vendor_name=r["vendor_name"],
        gstin=r["gstin"],
        invoice_date=date.fromisoformat(r["invoice_date"]),
        po_number=r["po_number"] or r["raw_po_number"],
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


def _reconcile_bundle_from_row(
    r: sqlite3.Row,
    conn: sqlite3.Connection,
    eval_labels: Dict[str, ExpectedResolution],
) -> UserInvoiceBundle:
    inv = _row_to_invoice(r)

    # Resolve PO
    po = None
    target_po = r["po_number"] or r["raw_po_number"]
    if target_po:
        po_row = conn.execute("SELECT * FROM purchase_orders WHERE po_number = ?", (target_po,)).fetchone()
        if po_row:
            po = PurchaseOrder(
                po_number=po_row["po_number"],
                vendor_name=po_row["vendor_name"],
                gstin=po_row["gstin"],
                issue_date=date.fromisoformat(po_row["issue_date"]),
                valid_until=date.fromisoformat(po_row["valid_until"]),
                item_description=po_row["item_description"],
                hsn_code=po_row["hsn_code"],
                unit_price_inr=Decimal(po_row["unit_price_inr"]),
                quantity=po_row["quantity"],
                total_excl_tax_inr=Decimal(po_row["total_excl_tax_inr"]),
                gst_rate=Decimal(po_row["gst_rate"]),
                gst_amount_inr=Decimal(po_row["gst_amount_inr"]),
                total_inr=Decimal(po_row["total_inr"]),
            )

    # Resolve GRN
    grn = None
    if r["grn_number"]:
        grn_row = conn.execute("SELECT * FROM goods_receipts WHERE grn_number = ?", (r["grn_number"],)).fetchone()
        if grn_row:
            grn = GoodsReceiptNote(
                grn_number=grn_row["grn_number"],
                po_number=grn_row["po_number"],
                receipt_date=date.fromisoformat(grn_row["receipt_date"]),
                received_quantity=grn_row["received_quantity"],
                accepted_quantity=grn_row["accepted_quantity"],
                rejected_quantity=grn_row["rejected_quantity"],
                inspection_notes=grn_row["inspection_notes"],
            )
    if not grn and target_po:
        grn_row = conn.execute(
            "SELECT * FROM goods_receipts WHERE po_number = ? ORDER BY receipt_date DESC LIMIT 1",
            (target_po,),
        ).fetchone()
        if grn_row:
            grn = GoodsReceiptNote(
                grn_number=grn_row["grn_number"],
                po_number=grn_row["po_number"],
                receipt_date=date.fromisoformat(grn_row["receipt_date"]),
                received_quantity=grn_row["received_quantity"],
                accepted_quantity=grn_row["accepted_quantity"],
                rejected_quantity=grn_row["rejected_quantity"],
                inspection_notes=grn_row["inspection_notes"],
            )

    if po:
        match_res = match_invoice(invoice=inv, po=po, grn=grn)
    else:
        raw_target = target_po or "NONE"
        match_res = MatchResult(
            is_match=False,
            exception_type=ExceptionType.NONE,
            invoice_number=inv.invoice_number,
            po_number=raw_target,
            vendor_name=inv.vendor_name,
            invoice_amount_inr=inv.total_inr,
            expected_amount_inr=Decimal("0.00"),
            explanation=f"Pending PO documentation: Purchase order '{raw_target}' is not yet in repository.",
            all_discrepancies=[
                Discrepancy(
                    exception_type=ExceptionType.NONE,
                    field="po_number",
                    invoice_value=raw_target,
                    expected_value="Valid PO in repository",
                    message=f"Purchase order '{raw_target}' was not found in database.",
                )
            ],
        )

    exp_res = eval_labels.get(inv.invoice_number)
    is_inc = bool(r["is_incomplete"]) if "is_incomplete" in r.keys() else (po is None)
    is_arc = bool(r["is_archived"]) if "is_archived" in r.keys() else False

    return UserInvoiceBundle(
        invoice=inv,
        po=po,
        grn=grn,
        match_result=match_res,
        is_user_created=bool(r["is_user_created"]),
        expected_resolution=exp_res,
        is_incomplete=is_inc,
        is_archived=is_arc,
    )


def _load_eval_labels() -> Dict[str, ExpectedResolution]:
    if not EVAL_LABELS_FILE.exists():
        return {}
    try:
        with open(EVAL_LABELS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k: ExpectedResolution.model_validate(v) for k, v in raw.items()}
    except Exception:
        return {}


def get_all_reconciled_invoices(db_path: Path = DB_PATH) -> List[UserInvoiceBundle]:
    """Retrieve all operational invoices (user records first, then benchmark fixtures) from SQLite."""
    init_db(db_path)
    eval_labels = _load_eval_labels()
    bundles: List[UserInvoiceBundle] = []
    with get_connection(db_path) as conn:
        inv_rows = conn.execute(
            """
            SELECT * FROM invoices
            ORDER BY is_user_created DESC,
                     CASE WHEN is_user_created = 1 THEN invoice_date END DESC,
                     rowid ASC
            """
        ).fetchall()
        for r in inv_rows:
            bundles.append(_reconcile_bundle_from_row(r, conn, eval_labels))
    return bundles


def get_user_invoices_reconciled(db_path: Path = DB_PATH) -> List[UserInvoiceBundle]:
    """Retrieve only user-created invoices from SQLite (backwards compatibility)."""
    init_db(db_path)
    eval_labels = _load_eval_labels()
    bundles: List[UserInvoiceBundle] = []
    with get_connection(db_path) as conn:
        inv_rows = conn.execute(
            "SELECT * FROM invoices WHERE is_user_created = 1 ORDER BY invoice_date DESC, rowid DESC"
        ).fetchall()
        for r in inv_rows:
            bundles.append(_reconcile_bundle_from_row(r, conn, eval_labels))
    return bundles


def get_invoice_record_by_id(invoice_number: str, db_path: Path = DB_PATH) -> Optional[UserInvoiceBundle]:
    """Retrieve a single invoice bundle by its invoice number across all operational records."""
    init_db(db_path)
    eval_labels = _load_eval_labels()
    with get_connection(db_path) as conn:
        r = conn.execute("SELECT * FROM invoices WHERE invoice_number = ?", (invoice_number,)).fetchone()
        if not r:
            return None
        return _reconcile_bundle_from_row(r, conn, eval_labels)


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
        with conn:
            # Check if an existing review is already present for this invoice
            existing = conn.execute(
                "SELECT * FROM human_reviews WHERE invoice_number = ?",
                (invoice_number,)
            ).fetchone()

            if existing:
                # Preserve existing review in review_audit_log before updating (audit trail preservation)
                ver_count = conn.execute(
                    "SELECT COUNT(*) FROM review_audit_log WHERE invoice_number = ?",
                    (invoice_number,)
                ).fetchone()[0]
                version = ver_count + 1

                conn.execute(
                    """
                    INSERT INTO review_audit_log (
                        invoice_number, version, decision, approver_role, approved_amount_inr,
                        rationale, hindsight_doc_id, hindsight_bank_id, hindsight_status,
                        reviewed_at, superseded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        existing["invoice_number"],
                        version,
                        existing["decision"],
                        existing["approver_role"],
                        existing["approved_amount_inr"],
                        existing["rationale"],
                        existing["hindsight_doc_id"],
                        existing["hindsight_bank_id"],
                        existing["hindsight_status"],
                        existing["reviewed_at"],
                        now_iso,
                    ),
                )

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


def get_review_history(invoice_number: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve historical superseded review versions for an invoice."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM review_audit_log WHERE invoice_number = ? ORDER BY version ASC",
            (invoice_number,)
        ).fetchall()
        return [dict(r) for r in rows]


def archive_invoice(invoice_number: str, db_path: Path = DB_PATH) -> bool:
    """Soft-delete/archive an invoice while strictly preserving its record and human reviews."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        res = conn.execute(
            "UPDATE invoices SET is_archived = 1 WHERE invoice_number = ?",
            (invoice_number,)
        )
        return res.rowcount > 0


def unarchive_invoice(invoice_number: str, db_path: Path = DB_PATH) -> bool:
    """Unarchive an invoice."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        res = conn.execute(
            "UPDATE invoices SET is_archived = 0 WHERE invoice_number = ?",
            (invoice_number,)
        )
        return res.rowcount > 0


def link_invoice_po(invoice_number: str, po_number: str, db_path: Path = DB_PATH) -> bool:
    """Manually link an incomplete invoice to an authentic existing Purchase Order."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        po_exists = conn.execute("SELECT 1 FROM purchase_orders WHERE po_number = ?", (po_number,)).fetchone()
        if not po_exists:
            raise ValueError(f"Purchase Order '{po_number}' does not exist in repository. Cannot link unverified PO.")
        res = conn.execute(
            "UPDATE invoices SET po_number = ?, raw_po_number = ?, is_incomplete = 0 WHERE invoice_number = ?",
            (po_number, po_number, invoice_number)
        )
        return res.rowcount > 0


def link_invoice_grn(invoice_number: str, grn_number: str, db_path: Path = DB_PATH) -> bool:
    """Manually link an invoice to an authentic existing Goods Receipt Note."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        grn_exists = conn.execute("SELECT 1 FROM goods_receipts WHERE grn_number = ?", (grn_number,)).fetchone()
        if not grn_exists:
            raise ValueError(f"Goods Receipt Note '{grn_number}' does not exist in repository. Cannot link unverified GRN.")
        res = conn.execute(
            "UPDATE invoices SET grn_number = ? WHERE invoice_number = ?",
            (grn_number, invoice_number)
        )
        return res.rowcount > 0


def list_incomplete_invoices(db_path: Path = DB_PATH) -> List[Invoice]:
    """List all invoices that currently lack a verified Purchase Order."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE is_incomplete = 1 OR po_number IS NULL ORDER BY invoice_date DESC"
        ).fetchall()
        return [_row_to_invoice(r) for r in rows]


def sync_pending_reviews(memory_client: Any, db_path: Path = DB_PATH) -> Dict[str, Any]:
    """
    Scans for human reviews in PENDING_SYNC, FAILED, or SAVED_LOCAL_PENDING_SYNC state
    and attempts synchronization if Hindsight is online. Idempotent and safe.
    """
    init_db(db_path)
    if not memory_client or not getattr(memory_client, "is_healthy", lambda: False)():
        return {"synced": 0, "failed": 0, "total_attempted": 0, "message": "Hindsight engine is offline. Sync deferred."}

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM human_reviews
            WHERE hindsight_status IN ('PENDING_SYNC', 'FAILED', 'SAVED_LOCAL_PENDING_SYNC')
            """
        ).fetchall()

        synced_count = 0
        failed_count = 0

        for r in rows:
            try:
                from agent.feedback import FeedbackSubmission, process_human_feedback
                from data.models import ApproverDecision, ApproverRole

                submission = FeedbackSubmission(
                    invoice_number=r["invoice_number"],
                    vendor_name="Pending Review",
                    exception_type="PENDING_REVIEW",
                    agent_proposal="Manual sync",
                    human_decision=ApproverDecision(r["decision"]),
                    approver_role=ApproverRole(r["approver_role"]),
                    human_explanation=r["rationale"],
                    final_amount_inr=Decimal(r["approved_amount_inr"]),
                    cited_memory_ids=[],
                )
                target_bank = r["hindsight_bank_id"] or LIVE_DEMO_BANK_ID
                res = process_human_feedback(
                    submission=submission,
                    memory_client=memory_client,
                    bank_id=target_bank,
                )
                if getattr(res, "hindsight_status", None) == "SYNCED" or getattr(memory_client, "last_retain_status", None) == "SYNCED":
                    conn.execute(
                        "UPDATE human_reviews SET hindsight_status = 'SYNCED', hindsight_doc_id = ? WHERE invoice_number = ?",
                        (res.document_id, r["invoice_number"])
                    )
                    synced_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

        return {"synced": synced_count, "failed": failed_count, "total_attempted": len(rows)}


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
