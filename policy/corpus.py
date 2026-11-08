"""
policy/corpus.py
────────────────────────────────────────────────────────────────────────────────
Fictional Corporate Accounts Payable Policy Corpus for LedgerMind.
Defines versioned internal policies with stable IDs, effective dates,
deterministic variance thresholds, and escalation pathways.

IMPORTANT: These documents represent internal synthetic enterprise policies,
not statutory Indian tax legislation.
"""

from datetime import date
from decimal import Decimal
from typing import List

from data.models import ApproverDecision, ExceptionType
from policy.models import CompanyPolicy


POLICIES: List[CompanyPolicy] = [
    # ─────────────────────────────────────────────────────────────────────────
    # POL-AP-001: Invoice Price Variance Tolerance Policy
    # ─────────────────────────────────────────────────────────────────────────
    CompanyPolicy(
        policy_id="POL-AP-001",
        version="1.0",
        title="Invoice Price Variance Tolerance Standard (Retired)",
        effective_from=date(2024, 1, 1),
        effective_to=date(2025, 6, 30),
        scope="All Enterprise Direct & Indirect Procurement Invoices",
        applicable_exception_types=[ExceptionType.PRICE_MISMATCH],
        primary_clause="Permitted price variance up to 2.5% with departmental supervisor sign-off.",
        full_policy_text=(
            "Clause 1.0 (Scope): Governs line item unit price deviations against approved Purchase Orders.\n"
            "Clause 1.1 (Tolerance): Unit price variance up to 2.50% above PO contracted rate may be approved "
            "by AP Accountant without procurement amendment, provided total invoice variance is under ₹10,000.\n"
            "Clause 1.2 (Over 2.5%): Price deviations exceeding 2.50% require AP Manager review."
        ),
        max_tolerance_percent=Decimal("2.50"),
        max_tolerance_inr=Decimal("10000.00"),
        mandated_action=ApproverDecision.APPROVED,
        authorized_escalation_path="AP Supervisor",
        is_statutory=False,
    ),
    CompanyPolicy(
        policy_id="POL-AP-001",
        version="2.0",
        title="Invoice Price Variance Tolerance & Underpayment Credit Standard",
        effective_from=date(2025, 7, 1),
        effective_to=None,
        scope="All Enterprise Direct & Indirect Procurement Invoices",
        applicable_exception_types=[ExceptionType.PRICE_MISMATCH],
        primary_clause=(
            "Contracted price tolerance is strictly 0.0%. Billed unit price overages between 1.0% and 5.0% "
            "must be EDITED down to PO contracted rate (underpayment credit). Approvers are strictly prohibited "
            "from approving unamended price overages above 1.0%. Price overages exceeding 5.0% must be REJECTED."
        ),
        full_policy_text=(
            "Clause 2.0 (Contract Grounding): All supplier billings must strictly adhere to executed Purchase Order unit rates.\n"
            "Clause 2.1 (Rounding Tolerance): Line item price variances up to 1.00% (and total delta <= ₹500.00) "
            "may be absorbed as clerical rounding.\n"
            "Clause 2.2 (Price Overcharges 1.0% to 5.0%): Where goods or services have been delivered satisfactorily "
            "but the supplier billed a unit price between 1.00% and 5.00% above PO rate, AP approvers MUST adjust (EDIT) "
            "the payable amount down to the contracted PO total. Approving unamended price overages without an official PO "
            "amendment is a direct financial controls violation.\n"
            "Clause 2.3 (Excessive Variance > 5.0%): Invoices with price overcharge exceeding 5.00% must be REJECTED and "
            "returned to supplier for a corrected invoice or credit note.\n"
            "Clause 2.4 (Escalation): Any supplier dispute regarding price adjustments must be escalated to Procurement Category Lead."
        ),
        max_tolerance_percent=Decimal("1.00"),
        max_tolerance_inr=Decimal("500.00"),
        mandated_action=ApproverDecision.EDITED,
        authorized_escalation_path="Procurement Category Lead / Finance Controller",
        is_statutory=False,
    ),

    # ─────────────────────────────────────────────────────────────────────────
    # POL-AP-002: Delivered Quantity Shortfall and Partial Intake Policy
    # ─────────────────────────────────────────────────────────────────────────
    CompanyPolicy(
        policy_id="POL-AP-002",
        version="1.0",
        title="Delivered Quantity Shortfall and Goods Receipt Reconciliation Policy",
        effective_from=date(2024, 1, 1),
        effective_to=None,
        scope="Physical Goods Inwarding, Warehouse Receipts, and Logistics",
        applicable_exception_types=[ExceptionType.QUANTITY_SHORTFALL],
        primary_clause=(
            "Payment is authorized exclusively for physically received and accepted units confirmed on the Goods "
            "Receipt Note (GRN). Where invoice billed quantity exceeds GRN accepted quantity, the invoice amount "
            "must be EDITED down to actual delivered units."
        ),
        full_policy_text=(
            "Clause 1.0 (Three-Way Physical Matching): Accounts Payable must reconcile supplier invoiced quantity against "
            "warehouse verified intake on the corresponding GRN.\n"
            "Clause 1.1 (Shortfall Adjustment): When invoiced quantity exceeds accepted quantity, AP must adjust the payable "
            "subtotal and GST proportionally to match accepted quantity only. Shortfall volume must not be paid.\n"
            "Clause 1.2 (Bulk Packaging Tolerance): For bulk agricultural and raw packaging goods, an intake variance of up to "
            "2.0% resulting from standard packaging container increments (e.g. 50 kg bags) may be approved if certified by "
            "warehouse intake QA remarks.\n"
            "Clause 1.3 (Escalation): Unresolved physical transit losses exceeding 10% must be escalated to Logistics Operations."
        ),
        max_tolerance_percent=Decimal("0.50"),
        max_tolerance_inr=Decimal("2000.00"),
        mandated_action=ApproverDecision.EDITED,
        authorized_escalation_path="Warehouse Operations Manager / AP Manager",
        is_statutory=False,
    ),

    # ─────────────────────────────────────────────────────────────────────────
    # POL-AP-003: Duplicate Invoice Prevention and Anti-Fraud Policy
    # ─────────────────────────────────────────────────────────────────────────
    CompanyPolicy(
        policy_id="POL-AP-003",
        version="1.0",
        title="Duplicate Invoice Identification, Prevention, and Anti-Fraud Policy",
        effective_from=date(2024, 1, 1),
        effective_to=None,
        scope="All Vendor Submissions & Payment Processing",
        applicable_exception_types=[ExceptionType.DUPLICATE_INVOICE],
        primary_clause=(
            "Zero tolerance for duplicate billings. Any invoice sharing the same invoice number, vendor GSTIN, "
            "or identical financial transaction hash with a previously processed or paid record must be REJECTED."
        ),
        full_policy_text=(
            "Clause 1.0 (Strict Prohibition): Double payment of supplier claims is strictly prohibited under corporate financial controls.\n"
            "Clause 1.1 (Automated Duplicate Check): The AP system checks supplier GSTIN, invoice number, PO reference, and total amount.\n"
            "Clause 1.2 (Action): If an invoice is confirmed as a duplicate submission of a prior claim, it must be REJECTED immediately. "
            "Under no circumstances may an approver approve, edit, or release funds for a duplicate record.\n"
            "Clause 1.3 (Repeat Offenders): Suppliers submitting duplicate claims more than twice in a fiscal quarter must be escalated "
            "to Internal Audit for supplier master file verification."
        ),
        max_tolerance_percent=Decimal("0.00"),
        max_tolerance_inr=Decimal("0.00"),
        mandated_action=ApproverDecision.REJECTED,
        authorized_escalation_path="Internal Audit / Fraud Prevention Committee",
        is_statutory=False,
    ),

    # ─────────────────────────────────────────────────────────────────────────
    # POL-AP-004: Purchase Order Validity and Expiration Policy
    # ─────────────────────────────────────────────────────────────────────────
    CompanyPolicy(
        policy_id="POL-AP-004",
        version="1.0",
        title="Purchase Order Validity and Lapsed Contract Grace Policy (Retired)",
        effective_from=date(2024, 1, 1),
        effective_to=date(2025, 7, 31),
        scope="All Purchase Orders & Annual Maintenance Contracts",
        applicable_exception_types=[ExceptionType.PO_EXPIRED],
        primary_clause="Permitted a 30-day grace extension for expired POs with AP Manager endorsement.",
        full_policy_text=(
            "Clause 1.0 (PO Validity): POs remain valid until stated expiration date.\n"
            "Clause 1.1 (Grace Period): Invoices received within 30 calendar days following PO expiration may be approved "
            "or escalated with AP Manager grace endorsement, provided goods/services delivery occurred prior to expiry."
        ),
        max_tolerance_percent=None,
        max_tolerance_inr=None,
        mandated_action=ApproverDecision.ESCALATED,
        authorized_escalation_path="AP Manager",
        is_statutory=False,
    ),
    CompanyPolicy(
        policy_id="POL-AP-004",
        version="2.0",
        title="Strict Purchase Order Expiration & Zero-Grace Standard (Policy 2025-Q3)",
        effective_from=date(2025, 8, 1),
        effective_to=None,
        scope="All Purchase Orders & Annual Maintenance Contracts",
        applicable_exception_types=[ExceptionType.PO_EXPIRED],
        primary_clause=(
            "Zero tolerance for expired Purchase Orders. Invoices received with an invoice date after the PO expiration "
            "date must be REJECTED. Retroactive grace extensions are strictly prohibited without formal CFO renewal."
        ),
        full_policy_text=(
            "Clause 2.0 (Expiration Enforcement): All procurement commitments lapse on 23:59:59 of the PO validity date.\n"
            "Clause 2.1 (Mandatory Rejection): Any supplier invoice billed against an expired PO must be REJECTED. "
            "AP approvers possess zero discretionary authority to approve or grant grace extensions for lapsed POs.\n"
            "Clause 2.2 (Retroactive Renewal): If services were delivered in good faith after expiration, the supplier must "
            "contact Procurement to issue a formal PO renewal or amendment signed by the Chief Financial Officer (CFO).\n"
            "Clause 2.3 (Escalation): Direct escalation to CFO is required for operational emergency renewals."
        ),
        max_tolerance_percent=Decimal("0.00"),
        max_tolerance_inr=Decimal("0.00"),
        mandated_action=ApproverDecision.REJECTED,
        authorized_escalation_path="Chief Financial Officer (CFO)",
        is_statutory=False,
    ),

    # ─────────────────────────────────────────────────────────────────────────
    # POL-AP-005: Statutory GST Rate and Tax Compliance Policy
    # ─────────────────────────────────────────────────────────────────────────
    CompanyPolicy(
        policy_id="POL-AP-005",
        version="1.0",
        title="Statutory GST Rate Integrity & Input Tax Credit (ITC) Protection Standard",
        effective_from=date(2024, 1, 1),
        effective_to=None,
        scope="All Invoices Subject to Indian Central and State GST Legislation",
        applicable_exception_types=[ExceptionType.GST_RATE_ERROR],
        primary_clause=(
            "Invoices charging incorrect GST rates cannot be approved or edited by AP, because tax input credit (ITC) "
            "requires valid tax invoices matching statutory schedules and GSTR-2B. Invoices with GST rate errors must be REJECTED."
        ),
        full_policy_text=(
            "Clause 1.0 (Statutory Protection): To protect enterprise Input Tax Credit (ITC) eligibility under Section 16 "
            "of the CGST Act, supplier tax invoices must strictly reflect statutory GST rates corresponding to product HSN/SAC.\n"
            "Clause 1.1 (Prohibition on Adjustment): Accounts Payable is legally prohibited from editing or adjusting tax rates "
            "on a supplier's tax document. Only the supplier can legally issue or amend tax invoices.\n"
            "Clause 1.2 (Mandatory Action): Invoices with statutory GST rate discrepancies (e.g. 12% billed vs 18% statutory) "
            "must be REJECTED. The supplier must cancel the defective e-invoice and reissue a compliant tax invoice.\n"
            "Clause 1.3 (Escalation): Escalation to Senior Tax Compliance Officer."
        ),
        max_tolerance_percent=Decimal("0.00"),
        max_tolerance_inr=Decimal("0.00"),
        mandated_action=ApproverDecision.REJECTED,
        authorized_escalation_path="Senior Tax Compliance Officer",
        is_statutory=True,
    ),

    # ─────────────────────────────────────────────────────────────────────────
    # POL-AP-006: HSN / SAC Code Verification Policy
    # ─────────────────────────────────────────────────────────────────────────
    CompanyPolicy(
        policy_id="POL-AP-006",
        version="1.0",
        title="HSN / SAC Code Harmonization and Tariff Classification Policy",
        effective_from=date(2024, 1, 1),
        effective_to=None,
        scope="All Purchase Orders & Supplier Tax Invoices",
        applicable_exception_types=[ExceptionType.HSN_MISMATCH],
        primary_clause=(
            "Where an HSN code mismatch does not alter the effective GST tax rate, AP may approve with a clerical "
            "reclassification note. If the HSN mismatch impacts the statutory tax rate, the invoice must be REJECTED."
        ),
        full_policy_text=(
            "Clause 1.0 (Harmonized System Compliance): Invoiced HSN/SAC codes must match contracted PO classifications.\n"
            "Clause 1.1 (Neutral Tax Impact): If the HSN mismatch carries identical statutory GST tax rates (e.g. both HSNs "
            "taxed at 18%), AP may approve the invoice provided a reclassification memo is logged in the audit trail.\n"
            "Clause 1.2 (Tax-Impacting Mismatch): If the HSN mismatch causes a tax rate discrepancy, the invoice must be REJECTED.\n"
            "Clause 1.3 (Escalation): Purchasing Category Specialist / Tax Accountant."
        ),
        max_tolerance_percent=None,
        max_tolerance_inr=None,
        mandated_action=ApproverDecision.APPROVED,
        authorized_escalation_path="Purchasing Category Specialist / Senior Tax Accountant",
        is_statutory=True,
    ),

    # ─────────────────────────────────────────────────────────────────────────
    # POL-AP-007: Financial Delegation of Authority & Approval Thresholds Policy
    # ─────────────────────────────────────────────────────────────────────────
    CompanyPolicy(
        policy_id="POL-AP-007",
        version="1.0",
        title="Financial Delegation of Authority & AP Approval Thresholds Standard",
        effective_from=date(2024, 1, 1),
        effective_to=None,
        scope="Enterprise Delegation of Authority (DoA)",
        applicable_exception_types=[
            ExceptionType.PRICE_MISMATCH,
            ExceptionType.QUANTITY_SHORTFALL,
            ExceptionType.DUPLICATE_INVOICE,
            ExceptionType.PO_EXPIRED,
            ExceptionType.GST_RATE_ERROR,
            ExceptionType.HSN_MISMATCH,
        ],
        primary_clause=(
            "Discrepancy resolution authority is capped: AP Accountant <= ₹50,000; AP Manager <= ₹500,000; "
            "Financial Controller <= ₹2,500,000; CFO > ₹2,500,000 or any policy exception override."
        ),
        full_policy_text=(
            "Clause 1.0 (Delegation Limits): Financial approval limits for resolving AP discrepancies:\n"
            "  - AP Accountant: Up to ₹50,000.00\n"
            "  - AP Manager: Up to ₹500,000.00\n"
            "  - Financial Controller: Up to ₹2,500,000.00\n"
            "  - Chief Financial Officer (CFO): Exceeding ₹2,500,000.00 or any policy exception override.\n"
            "Clause 1.1 (Escalation Requirement): Any transaction exceeding the reviewer's DoA ceiling must be ESCALATED."
        ),
        max_tolerance_percent=None,
        max_tolerance_inr=None,
        mandated_action=None,
        authorized_escalation_path="Financial Controller / CFO",
        is_statutory=False,
    ),
]

