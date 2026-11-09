"""
ui/state.py
────────────────────────────────────────────────────────────────────────────────
Session State Management and Data Providers for LedgerMind Streamlit App.
Provides cached singletons, thread-safe session variables, and Hindsight health checks.
"""

from decimal import Decimal
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
import streamlit as st

from agent.resolver import ResolutionAgent, ResolutionProposal
from config import BASELINE_EVAL_BANK_ID, LIVE_DEMO_BANK_ID
from data.models import HeldOutInvoice, HistoricalDecision
from data.synthetic import load_held_out_invoices
from memory.client import MemoryClient
from memory.schema import MemoryMode

ROOT_DIR = Path(__file__).resolve().parent.parent


def init_session_state() -> None:
    """Initialize all session state keys safely."""
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "Overview"

    if "selected_invoice_id" not in st.session_state:
        st.session_state["selected_invoice_id"] = "INV-PI-2025-101"

    if "reviewed_invoices" not in st.session_state:
        try:
            from data.store import get_all_human_reviews
            st.session_state["reviewed_invoices"] = get_all_human_reviews()
        except Exception:
            st.session_state["reviewed_invoices"] = {}

    if "proposal_cache" not in st.session_state:
        st.session_state["proposal_cache"] = {}

    if "comparison_cache" not in st.session_state:
        st.session_state["comparison_cache"] = {}

    if "last_submission_token" not in st.session_state:
        st.session_state["last_submission_token"] = None

    if "submission_feedback_msg" not in st.session_state:
        st.session_state["submission_feedback_msg"] = None


def get_all_invoices() -> List[Any]:
    """
    Load all active invoices:
    1. Newly created / imported user invoices from SQLite (is_user_created=True).
    2. The 20 baseline synthetic benchmark invoices (is_user_created=False).
    """
    sample_invoices = load_held_out_invoices()

    try:
        from data.store import get_user_invoices_reconciled
        user_invoices = get_user_invoices_reconciled()
    except Exception:
        user_invoices = []

    return user_invoices + sample_invoices


def get_held_out_invoices() -> List[Any]:
    """Retrieve full invoice list (backwards-compatible alias for queue and workbench)."""
    return get_all_invoices()


def get_held_out_by_id(invoice_number: str) -> Optional[Any]:
    """Retrieve an invoice by its invoice number across sample and user records."""
    invoices = get_all_invoices()
    for inv in invoices:
        if inv.invoice.invoice_number == invoice_number:
            return inv
    return None


@st.cache_resource
def get_memory_client() -> MemoryClient:
    """Initialize and cache the global MemoryClient."""
    return MemoryClient()


@st.cache_resource
def get_resolution_agent() -> ResolutionAgent:
    """Initialize and cache the ResolutionAgent with the MemoryClient."""
    client = get_memory_client()
    return ResolutionAgent(memory_client=client, default_bank_id=LIVE_DEMO_BANK_ID)


def check_hindsight_health() -> Dict[str, Any]:
    """Check live connectivity to Hindsight API container or cloud endpoint."""
    client = get_memory_client()
    base_url = client.base_url or os.getenv("HINDSIGHT_LOCAL_URL", "http://localhost:8888")
    configured_mode = getattr(client, "configured_mode", client.mode)

    if configured_mode == MemoryMode.OFFLINE or base_url.startswith("offline://"):
        return {
            "status": "OFFLINE_MODE",
            "connected": False,
            "url": "offline://local",
            "message": "Running in offline fallback mode (JSONL persistence).",
        }

    try:
        health_url = f"{base_url.rstrip('/')}/health"
        resp = requests.get(health_url, timeout=2.0)
        if resp.status_code == 200:
            client.is_healthy()  # Ensure client re-attaches live mode
            return {
                "status": "ONLINE",
                "connected": True,
                "url": base_url,
                "status_code": 200,
                "message": "Hindsight vector memory engine is healthy and reachable.",
            }
        else:
            return {
                "status": "DEGRADED",
                "connected": False,
                "url": base_url,
                "status_code": resp.status_code,
                "message": f"Hindsight returned status code {resp.status_code}.",
            }
    except Exception as e:
        return {
            "status": "UNREACHABLE",
            "connected": False,
            "url": base_url,
            "error": str(e),
            "message": f"Could not reach Hindsight at {base_url} ({e}). Using offline store fallback.",
        }


def get_hindsight_document_count(bank_id: str) -> Tuple[int, int]:
    """
    Authoritatively check document count in a Hindsight bank.
    Returns:
        (unique_document_count, total_memory_facts_count)
    """
    client = get_memory_client()
    health = check_hindsight_health()
    if not health.get("connected") or client.mode == MemoryMode.OFFLINE or not client._sdk_client:
        all_records = client.offline_store.get_all(bank_id=bank_id)
        unique_docs = {r.get("document_id") for r in all_records if r.get("document_id")}
        return len(unique_docs), len(all_records)

    try:
        mems = client._sdk_client.list_memories(bank_id=bank_id)
        if mems and hasattr(mems, "items") and mems.items:
            doc_ids = set()
            for item in mems.items:
                doc_id = getattr(item, "document_id", None)
                if doc_id:
                    doc_ids.add(doc_id)
            return len(doc_ids), len(mems.items)
        return 0, 0
    except Exception:
        # Fall back to checking offline store count
        all_records = client.offline_store.get_all(bank_id=bank_id)
        unique_docs = {r.get("document_id") for r in all_records if r.get("document_id")}
        return len(unique_docs), len(all_records)
