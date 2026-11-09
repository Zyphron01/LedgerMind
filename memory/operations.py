"""
memory/operations.py
────────────────────────────────────────────────────────────────────────────────
Domain-Specific Memory Operations for LedgerMind.

Translates AP domain concepts (Invoices, MatchResults, Vendors) into
deterministic queries, tag filters, and retention payloads for Hindsight.
"""

from typing import List, Optional

from data.models import ExceptionType, Invoice, MatchResult
from data.vendors import get_vendor_slug
from memory.client import MemoryClient
from memory.schema import FeedbackRecord, RecalledMemory, ReflectSummary


def build_recall_query(invoice: Invoice, match_result: MatchResult) -> str:
    """Construct an information-dense AP query for semantic search."""
    disc = match_result.primary_discrepancy
    disc_text = disc.message if disc else "No primary discrepancy detected."
    return (
        f"Vendor: {invoice.vendor_name}. "
        f"Invoice: {invoice.invoice_number} for ₹{invoice.total_inr:,.2f}. "
        f"Exception: {match_result.exception_type.value}. "
        f"Discrepancy: {disc_text}. "
        f"What was the human approver decision and resolution rationale in past comparable cases?"
    )


def recall_for_exception(
    client: MemoryClient,
    bank_id: str,
    invoice: Invoice,
    match_result: MatchResult,
    limit: int = 5,
    min_score: Optional[float] = None,
) -> List[RecalledMemory]:
    """
    Retrieve past institutional decisions most relevant to the current discrepancy.
    Scoped by vendor and exception type.
    """
    vendor_slug = get_vendor_slug(invoice.vendor_name)
    raw_slug = invoice.vendor_name.lower().replace(" ", "-").replace(".", "")
    exc_type = match_result.exception_type.value.lower()

    # Search with primary query and tag scoping (support both canonical slug and raw seed slug)
    query = build_recall_query(invoice, match_result)
    tags = [f"vendor:{vendor_slug}", f"exception:{exc_type}"]
    if raw_slug != vendor_slug:
        tags.append(f"vendor:{raw_slug}")

    results = client.recall(
        bank_id=bank_id,
        query=query,
        tags=tags,
        limit=limit,
        min_score=min_score,
    )

    # Fallback to broader vendor recall if tag-specific recall yielded no results
    if not results:
        broad_tags = [f"vendor:{vendor_slug}"]
        if raw_slug != vendor_slug:
            broad_tags.append(f"vendor:{raw_slug}")
        results = client.recall(
            bank_id=bank_id,
            query=query,
            tags=broad_tags,
            limit=limit,
            min_score=min_score,
        )

    return results


def recall_for_confidence(
    client: MemoryClient,
    bank_id: str,
    vendor_slug: str,
    exception_type: ExceptionType,
    limit: int = 15,
    vendor_name: Optional[str] = None,
) -> List[RecalledMemory]:
    """
    Retrieve a broader sample of past comparable decisions for the confidence formula.
    Filtered strictly by vendor and exception type to avoid cross-context noise.
    """
    slug = vendor_slug.strip().lower()
    exc_str = exception_type.value.lower()
    tags = [f"vendor:{slug}", f"exception:{exc_str}"]
    if vendor_name:
        raw_slug = vendor_name.lower().replace(" ", "-").replace(".", "")
        if raw_slug != slug:
            tags.append(f"vendor:{raw_slug}")

    return client.recall(
        bank_id=bank_id,
        query=f"Past resolution decisions for {slug} with exception {exc_str}",
        tags=tags,
        limit=limit,
    )


def retain_human_feedback(
    client: MemoryClient,
    bank_id: str,
    feedback: FeedbackRecord,
) -> str:
    """
    Retain human review decision and explanation to institutional memory.
    Uses stable document_id (feedback-{invoice_number}) to prevent duplication.
    """
    return client.retain(
        bank_id=bank_id,
        content=feedback.to_narrative(),
        timestamp=feedback.timestamp.isoformat(),
        document_id=feedback.document_id,
        tags=feedback.to_tags(),
        metadata=feedback.to_metadata(),
        context="accounts-payable exception resolution",
    )


def get_vendor_profile(
    client: MemoryClient,
    bank_id: str,
    vendor_slug: str,
    force_refresh: bool = False,
) -> ReflectSummary:
    """Fetch synthesized vendor profile with automatic disk caching."""
    return client.reflect(
        bank_id=bank_id,
        vendor_slug=vendor_slug,
        force_refresh=force_refresh,
    )

