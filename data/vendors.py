"""
data/vendors.py
────────────────────────────────────────────────────────────────────────────────
Canonical definitions of the 8 Fictional Indian Business Suppliers.
Format-valid synthetic GSTINs, realistic HSN/SAC codes, spend categories,
and documented behavioral quirks for institutional AP exception learning.
"""

from decimal import Decimal
from typing import Dict
from data.models import ApproverDecision, Vendor


VENDORS_BY_SLUG: Dict[str, Vendor] = {
    "prabhav-infosystems": Vendor(
        name="Prabhav Infosystems Pvt Ltd",
        slug="prabhav-infosystems",
        gstin="27AABCP4821K1ZT",  # Maharashtra (27)
        city="Pune",
        state="Maharashtra",
        state_code="27",
        category="IT Consulting & Software Maintenance",
        standard_hsn="998314",
        standard_gst_rate=Decimal("0.18"),
        quirk_description="Creeping price overcharge (invoice unit rate 2% to 5% above contracted PO rate).",
        dominant_action=ApproverDecision.EDITED,
    ),
    "kamalnath-supplies": Vendor(
        name="Kamalnath Supplies Co",
        slug="kamalnath-supplies",
        gstin="29AABCK7735M1ZQ",  # Karnataka (29)
        city="Bengaluru",
        state="Karnataka",
        state_code="29",
        category="Hardware, Peripherals & Office Assets",
        standard_hsn="84714900",
        standard_gst_rate=Decimal("0.18"),
        quirk_description="Frequent duplicate invoice resubmissions (same invoice submitted 10-20 days later).",
        dominant_action=ApproverDecision.REJECTED,
    ),
    "devanshi-logistics": Vendor(
        name="Devanshi Logistics LLP",
        slug="devanshi-logistics",
        gstin="09AABCD2914R1ZP",  # Uttar Pradesh (09)
        city="Noida",
        state="Uttar Pradesh",
        state_code="09",
        category="Freight, Transport & Dispatch Services",
        standard_hsn="996812",
        standard_gst_rate=Decimal("0.18"),
        quirk_description="Delivers 75% to 85% of contracted volume, plus occasional freight HSN clerical mismatch.",
        dominant_action=ApproverDecision.APPROVED,
    ),
    "suryakant-engineering": Vendor(
        name="Suryakant Engineering Works",
        slug="suryakant-engineering",
        gstin="24AABCS6183H1ZG",  # Gujarat (24)
        city="Vadodara",
        state="Gujarat",
        state_code="24",
        category="Heavy Industrial Fabricated Parts",
        standard_hsn="73269099",
        standard_gst_rate=Decimal("0.18"),
        quirk_description="Invoices consistently arrive 15-30 days after PO validity date has expired.",
        dominant_action=ApproverDecision.REJECTED,  # Note: Temporal shift in pre/post 2025-08
    ),
    "narmada-pharma": Vendor(
        name="Narmada Pharma Distributors",
        slug="narmada-pharma",
        gstin="33AAACN3047J1ZE",  # Tamil Nadu (33)
        city="Chennai",
        state="Tamil Nadu",
        state_code="33",
        category="Bulk Chemical Reagents & Pharmaceutical Consumables",
        standard_hsn="30049099",
        standard_gst_rate=Decimal("0.18"),
        quirk_description="Applies 12% GST instead of standard statutory 18% GST.",
        dominant_action=ApproverDecision.REJECTED,
    ),
    "bhavna-textiles": Vendor(
        name="Bhavna Textile Traders",
        slug="bhavna-textiles",
        gstin="06AABCB5592F1ZL",  # Haryana (06)
        city="Panipat",
        state="Haryana",
        state_code="06",
        category="Industrial Uniforms, Linens & Technical Fabrics",
        standard_hsn="52081190",
        standard_gst_rate=Decimal("0.05"),
        quirk_description="Minor price variance (1% to 3% above PO) due to raw cotton indexation fluctuations.",
        dominant_action=ApproverDecision.APPROVED,
    ),
    "triveni-agro": Vendor(
        name="Triveni Agro Processors",
        slug="triveni-agro",
        gstin="21AABCT8841N1ZS",  # Odisha (21)
        city="Bhubaneswar",
        state="Odisha",
        state_code="21",
        category="Agricultural Raw Materials & Starch Compounds",
        standard_hsn="21069099",
        standard_gst_rate=Decimal("0.12"),
        quirk_description="Delivered weight rounded down to nearest 50 kg packaging bag unit.",
        dominant_action=ApproverDecision.APPROVED,
    ),
    "chintamani-tech": Vendor(
        name="Chintamani Tech Solutions",
        slug="chintamani-tech",
        gstin="32AAACC4219P1ZW",  # Kerala (32)
        city="Kochi",
        state="Kerala",
        state_code="32",
        category="Cloud Infrastructure & Managed NOC Hosting",
        standard_hsn="998315",
        standard_gst_rate=Decimal("0.18"),
        quirk_description="Emergency service invoices billed against expired annual support contract POs (PO_EXPIRED).",
        dominant_action=ApproverDecision.APPROVED,
    ),
}

import re

LEGAL_ENTITY_WORDS = {
    "pvt", "ltd", "private", "limited", "llp", "co", "company", "inc",
    "corp", "corporation", "enterprises"
}

ALL_VENDORS = list(VENDORS_BY_SLUG.values())


def get_vendor_slug(name_or_slug: str) -> str:
    """Resolve vendor name or partial string to canonical vendor slug."""
    clean = re.sub(r"[^\w\s-]", "", name_or_slug.strip().lower())
    clean_hyphen = clean.replace(" ", "-")
    for v in ALL_VENDORS:
        if v.slug == clean or v.slug == clean_hyphen or v.name.lower() == clean:
            return v.slug
        if v.slug in clean or (len(clean) >= 6 and clean in v.slug):
            return v.slug
        v_words = {w for w in re.sub(r"[^\w\s-]", "", v.name.lower()).split() if w not in LEGAL_ENTITY_WORDS}
        clean_words = {w for w in clean.replace("-", " ").split() if w not in LEGAL_ENTITY_WORDS}
        overlap = v_words.intersection(clean_words)
        if len(overlap) >= 2:
            return v.slug
        if len(overlap) == 1 and overlap.intersection({
            "prabhav", "kamalnath", "devanshi", "suryakant", "narmada", "bhavna", "triveni", "chintamani"
        }):
            return v.slug
    # Unknown or custom vendor: derive slug without legal entity noise
    meaningful = [w for w in clean.replace("-", " ").split() if w not in LEGAL_ENTITY_WORDS]
    if meaningful:
        return "-".join(meaningful)
    return re.sub(r"[^a-z0-9]+", "-", clean).strip("-")
