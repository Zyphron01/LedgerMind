"""
policy/models.py
────────────────────────────────────────────────────────────────────────────────
Data models for LedgerMind Company Policy Corpus and Policy-Precedent Conflict Detection.
Defines versioned internal AP policies, conflict states, and evaluation records.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from data.models import ApproverDecision, ExceptionType


class ConflictStatus(str, Enum):
    """Evaluation status comparing applicable company policy against historical precedents."""
    COMPLIANT_PRECEDENT = "COMPLIANT_PRECEDENT"
    POLICY_PRECEDENT_CONFLICT = "POLICY_PRECEDENT_CONFLICT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    POLICY_UNKNOWN = "POLICY_UNKNOWN"
    POLICY_VERSION_CHANGED = "POLICY_VERSION_CHANGED"


class CompanyPolicy(BaseModel):
    """
    Versioned synthetic internal accounts payable policy document.
    Represents internal enterprise operating rules (distinct from statutory Indian tax law).
    """
    policy_id: str = Field(description="Unique stable policy identifier (e.g. POL-AP-001)")
    version: str = Field(description="Policy version string (e.g. 1.0, 2.0)")
    title: str = Field(description="Human-readable title of policy standard")
    effective_from: date = Field(description="Date on which policy version became active")
    effective_to: Optional[date] = Field(default=None, description="Date on which policy version expired (None if current)")
    scope: str = Field(description="Operational scope (e.g. Enterprise Procurement, Service Contracts)")
    applicable_exception_types: List[ExceptionType] = Field(description="3-way match exception types governed by this policy")
    primary_clause: str = Field(description="Core operational directive text")
    full_policy_text: str = Field(description="Full text of policy rules, tolerances, and escalation requirements")
    max_tolerance_percent: Optional[Decimal] = Field(default=None, description="Maximum permitted variance percentage (e.g. 1.0 for 1%)")
    max_tolerance_inr: Optional[Decimal] = Field(default=None, description="Maximum permitted monetary variance in INR")
    mandated_action: Optional[ApproverDecision] = Field(default=None, description="Mandatory decision when discrepancy exceeds tolerance")
    authorized_escalation_path: str = Field(description="Mandatory escalation role or committee")
    is_statutory: bool = Field(default=False, description="True if reflecting statutory tax rule (e.g. GST ITC), False if internal corporate policy")


class PolicyConflictEvaluation(BaseModel):
    """
    Outcome of comparing current invoice discrepancy, applicable written policy,
    and historical decisions retrieved from Hindsight memory.
    """
    status: ConflictStatus = Field(description="Detected relationship between policy and precedent")
    policy_id: Optional[str] = Field(default=None, description="Applicable policy identifier")
    policy_version: Optional[str] = Field(default=None, description="Applicable policy version")
    policy_title: Optional[str] = Field(default=None, description="Applicable policy title")
    quoted_clause: Optional[str] = Field(default=None, description="Directly quoted text excerpt from governing policy")
    sample_size_n: int = Field(default=0, description="Number of unique historical decisions evaluated")
    conflicting_document_ids: List[str] = Field(default_factory=list, description="Historical document IDs that violated policy")
    compliant_document_ids: List[str] = Field(default_factory=list, description="Historical document IDs that complied with policy")
    explanation: str = Field(description="Deterministic audit explanation of findings")
    requires_escalation: bool = Field(default=False, description="True if conflict or policy mandates human escalation")
    recommended_action: Optional[ApproverDecision] = Field(default=None, description="Policy-governed recommended action")
    escalation_path: Optional[str] = Field(default=None, description="Designated escalation authority")

