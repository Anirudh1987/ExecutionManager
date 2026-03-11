"""India-specific regulatory checks, approval sequencing, and industry risks.

Activated when deal_context.jurisdiction contains "india". Provides:
1. Regulatory compliance checks with legal citations
2. Approval sequencing with timelines and dependencies
3. Industry-specific regulatory risks
"""

from __future__ import annotations

from src.models.contract import ClauseType
from src.models.review import DealContext, RiskLevel


# ---------------------------------------------------------------------------
# Part A: Regulatory checks with legal citations
# ---------------------------------------------------------------------------

INDIA_REGULATORY_CHECKS: dict[str, dict] = {
    "fema_pricing": {
        "description": (
            "FEMA pricing guidelines — floor price for incoming investment "
            "(Rule 21, FEMA NDI Rules 2019), ceiling price for outbound transfer"
        ),
        "legal_citation": (
            "FEMA (Non-Debt Instruments) Rules 2019, Rule 21; "
            "RBI Master Direction on FDI dated Jan 4, 2018"
        ),
        "applies_to": [ClauseType.PURCHASE_PRICE],
        "keywords": ["valuation", "price per share", "fair market value", "dcf", "nav"],
        "investor_risk": RiskLevel.CRITICAL,
        "promoter_risk": RiskLevel.HIGH,
    },
    "sebi_sast": {
        "description": (
            "SEBI Substantial Acquisition of Shares and Takeovers Regulations 2011 — "
            "open offer at 25%, creeping acquisition 5%/year"
        ),
        "legal_citation": "SEBI (SAST) Regulations 2011, Regulations 3(1), 3(2), 4",
        "applies_to": [ClauseType.PURCHASE_PRICE, ClauseType.CONDITIONS_PRECEDENT],
        "keywords": ["open offer", "takeover", "acquisition", "threshold", "trigger"],
        "investor_risk": RiskLevel.CRITICAL,
        "promoter_risk": RiskLevel.MEDIUM,
    },
    "cci_approval": {
        "description": (
            "CCI combination approval if assets >₹2000 Cr or turnover >₹6000 Cr (India) "
            "or assets >₹8000 Cr or turnover >₹24000 Cr (global)"
        ),
        "legal_citation": (
            "Competition Act 2002, Section 5; CCI (Procedure in regard to transaction "
            "of business relating to combinations) Regulations 2011"
        ),
        "applies_to": [ClauseType.CONDITIONS_PRECEDENT],
        "keywords": ["competition", "antitrust", "cci", "combination", "merger control"],
        "investor_risk": RiskLevel.HIGH,
        "promoter_risk": RiskLevel.HIGH,
    },
    "fdi_sectoral_caps": {
        "description": (
            "FDI sectoral cap limits — automatic vs government approval route "
            "per DPIIT consolidated FDI policy"
        ),
        "legal_citation": "Consolidated FDI Policy 2020 (DPIIT); FEMA (NDI) Rules 2019, Schedule I",
        "applies_to": [ClauseType.CONDITIONS_PRECEDENT, ClauseType.PURCHASE_PRICE],
        "keywords": ["foreign direct investment", "fdi", "sectoral cap", "automatic route", "government route"],
        "investor_risk": RiskLevel.CRITICAL,
        "promoter_risk": RiskLevel.MEDIUM,
    },
    "stamp_duty": {
        "description": "State-specific stamp duty on share transfer instruments and agreements",
        "legal_citation": "Indian Stamp Act 1899 (as amended by states); specific rates vary by state",
        "applies_to": [ClauseType.TAX, ClauseType.CLOSING_MECHANICS],
        "keywords": ["stamp duty", "stamp paper", "franking", "adjudication"],
        "investor_risk": RiskLevel.MEDIUM,
        "promoter_risk": RiskLevel.MEDIUM,
    },
    "companies_act_s188": {
        "description": (
            "Companies Act 2013 Section 188/189 — related party transaction "
            "approval requirements"
        ),
        "legal_citation": (
            "Companies Act 2013, Sections 188, 189; "
            "Companies (Meetings of Board and its Powers) Rules 2014"
        ),
        "applies_to": [ClauseType.RESERVED_MATTERS, ClauseType.COVENANTS],
        "keywords": ["related party", "arm's length", "board approval", "special resolution"],
        "investor_risk": RiskLevel.HIGH,
        "promoter_risk": RiskLevel.HIGH,
    },
    "capital_gains": {
        "description": (
            "LTCG on unlisted shares (>24 months: 12.5%) vs STCG (applicable slab rate); "
            "withholding under S.195/196"
        ),
        "legal_citation": (
            "Income Tax Act 1961, Sections 45, 48, 112A, 195; "
            "Finance Act 2024 amendments"
        ),
        "applies_to": [ClauseType.TAX, ClauseType.PURCHASE_PRICE],
        "keywords": ["capital gain", "withholding", "tds", "section 195", "ltcg", "stcg"],
        "investor_risk": RiskLevel.HIGH,
        "promoter_risk": RiskLevel.CRITICAL,
    },
    "rbi_regulated_sectors": {
        "description": (
            "RBI prior approval for investment in banking, NBFC, "
            "insurance intermediary, payment systems"
        ),
        "legal_citation": (
            "Banking Regulation Act 1949, S.12B; "
            "RBI Master Direction on ownership in private banks"
        ),
        "applies_to": [ClauseType.CONDITIONS_PRECEDENT],
        "keywords": ["rbi approval", "banking", "nbfc", "payment", "insurance"],
        "investor_risk": RiskLevel.HIGH,
        "promoter_risk": RiskLevel.MEDIUM,
    },
}


# ---------------------------------------------------------------------------
# Part B: Regulatory approval sequencing with timelines
# ---------------------------------------------------------------------------

APPROVAL_SEQUENCE: dict[str, list[dict]] = {
    "pe_investment": [
        {"step": "Board resolution approving investment terms", "timeline": "1-2 weeks", "dependency": None},
        {"step": "FEMA pricing certification (CA certificate for fair value)", "timeline": "2-3 weeks", "dependency": "board_resolution"},
        {"step": "CCI filing (if thresholds exceeded)", "timeline": "30-60 days (Phase I) / 150 days (Phase II)", "dependency": "board_resolution"},
        {"step": "FDI government route approval (if applicable)", "timeline": "8-12 weeks", "dependency": "board_resolution"},
        {"step": "RBI approval (if regulated sector)", "timeline": "4-8 weeks", "dependency": "board_resolution"},
        {"step": "Shareholder resolution (if >25% equity or RPT)", "timeline": "21 days notice + meeting", "dependency": "board_resolution"},
        {"step": "SHA/SPA execution", "timeline": "Post all approvals", "dependency": "all_regulatory"},
        {"step": "FC-GPR filing with RBI (within 30 days of allotment)", "timeline": "30 days post-closing", "dependency": "closing"},
        {"step": "ROC filing (Form PAS-3 within 15 days of allotment)", "timeline": "15 days post-closing", "dependency": "closing"},
    ],
    "acquisition": [
        {"step": "Board resolution of both entities", "timeline": "1-2 weeks", "dependency": None},
        {"step": "Due diligence completion", "timeline": "4-8 weeks", "dependency": None},
        {"step": "CCI combination filing", "timeline": "30-150 days", "dependency": "board_resolution"},
        {"step": "SEBI open offer (if listed target, >25% trigger)", "timeline": "10 WDs to make offer; 15 days acceptance", "dependency": "board_resolution"},
        {"step": "NCLT approval (if scheme of arrangement)", "timeline": "4-6 months", "dependency": "board_resolution"},
        {"step": "SPA execution and signing", "timeline": "Post regulatory approvals", "dependency": "all_regulatory"},
        {"step": "Closing and share transfer", "timeline": "Per SPA long-stop date", "dependency": "signing"},
        {"step": "Stamp duty payment on transfer instruments", "timeline": "At or before closing", "dependency": "closing"},
    ],
}


def get_approval_sequence(deal_type: str) -> list[dict]:
    """Get the regulatory approval sequence for a deal type."""
    return APPROVAL_SEQUENCE.get(deal_type, APPROVAL_SEQUENCE.get("pe_investment", []))


# ---------------------------------------------------------------------------
# Part C: Industry-specific regulatory risks
# ---------------------------------------------------------------------------

INDIA_INDUSTRY_RISKS: dict[str, dict] = {
    "banking": {
        "regulators": ["RBI"],
        "key_risks": [
            "Promoter fit-and-proper criteria",
            "5%/10%/26% shareholding thresholds require RBI approval",
            "Voting rights cap at 26%",
        ],
        "fdi_limit": "74% (automatic route up to 49%, govt route 49-74%)",
        "special_conditions": [
            "Indian management control required",
            "At least 26% must be held by Indian residents",
        ],
    },
    "insurance": {
        "regulators": ["IRDAI"],
        "key_risks": [
            "Indian promoter must retain 26% for 10 years (recently relaxed)",
            "FDI limit increased to 74% in 2021",
        ],
        "fdi_limit": "74% (automatic route)",
        "special_conditions": [
            "Indian management and control conditions apply above 49%",
        ],
    },
    "telecom": {
        "regulators": ["TRAI", "DoT"],
        "key_risks": [
            "Spectrum transfer requires DoT approval",
            "Security clearance for foreign investors",
        ],
        "fdi_limit": "100% (automatic route)",
        "special_conditions": ["Security conditions for foreign investment"],
    },
    "pharma": {
        "regulators": ["CDSCO", "DPIIT"],
        "key_risks": [
            "Brownfield pharma FDI requires government route",
            "Manufacturing license transfer",
        ],
        "fdi_limit": "100% (greenfield automatic, brownfield govt route)",
        "special_conditions": ["DPIIT approval for brownfield investments"],
    },
    "fintech": {
        "regulators": ["RBI", "SEBI"],
        "key_risks": [
            "Digital lending guidelines (RBI Sept 2022)",
            "Data localization requirements",
            "Payment aggregator license",
        ],
        "fdi_limit": "100% (automatic route)",
        "special_conditions": [
            "Compliance with RBI digital lending guidelines mandatory",
        ],
    },
    "real_estate": {
        "regulators": ["RERA authorities"],
        "key_risks": [
            "RERA registration transfer",
            "Minimum 51% domestic ownership for real estate business",
        ],
        "fdi_limit": "100% (automatic route, subject to conditions)",
        "special_conditions": [
            "Minimum capitalization $5M",
            "3-year lock-in on original investment",
        ],
    },
    "defence": {
        "regulators": ["MoD", "DPIIT"],
        "key_risks": [
            "Security clearance mandatory",
            "Offset obligations above certain thresholds",
        ],
        "fdi_limit": "74% (auto up to 49%, govt 49-74%, beyond 74% case-by-case)",
        "special_conditions": [
            "Indian management and control required",
            "Security clearance from MHA",
        ],
    },
    "edtech": {
        "regulators": ["DPIIT"],
        "key_risks": [
            "Digital Personal Data Protection Act compliance",
            "NEP 2020 alignment",
        ],
        "fdi_limit": "100% (automatic route)",
        "special_conditions": ["Data localization for student data"],
    },
    "e_commerce": {
        "regulators": ["DPIIT", "CCI"],
        "key_risks": [
            "Marketplace vs inventory model distinction",
            "Press Note 2 (2018) restrictions",
        ],
        "fdi_limit": "100% marketplace model (automatic), 0% inventory model",
        "special_conditions": [
            "No entity-specific deep discounting",
            "No exclusive arrangements",
        ],
    },
}


def get_industry_risks(industry: str) -> dict | None:
    """Get industry-specific regulatory risks."""
    return INDIA_INDUSTRY_RISKS.get(industry.lower().replace(" ", "_"))


def get_applicable_regulatory_checks(
    clause_type: ClauseType,
    deal_context: DealContext,
) -> list[dict]:
    """Get regulatory checks applicable to a specific clause type and context.

    Only returns checks when jurisdiction is India.
    """
    if not deal_context.jurisdiction or "india" not in deal_context.jurisdiction.lower():
        return []

    applicable = []
    for check_id, check in INDIA_REGULATORY_CHECKS.items():
        if clause_type in check["applies_to"]:
            # Determine risk based on perspective
            client_side = deal_context.client_side
            if client_side in ("investor", "buyer"):
                risk = check["investor_risk"]
            else:
                risk = check["promoter_risk"]

            applicable.append({
                "check_id": check_id,
                "description": check["description"],
                "legal_citation": check["legal_citation"],
                "risk_level": risk,
                "keywords": check["keywords"],
            })

    return applicable
