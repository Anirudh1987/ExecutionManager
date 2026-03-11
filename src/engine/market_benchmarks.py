"""Indian PE/M&A market benchmark data for clause comparison.

Provides quantitative benchmarks from Indian market practice, organized
by clause type and deal structure. Used to contextualize AI findings with
statements like "Your cap at 1% is at the 5th percentile — well below
market median of 15%."
"""

from __future__ import annotations

from src.models.contract import ClauseType


# Percentile data: p25 (conservative), median, p75 (aggressive)
INDIA_MARKET_BENCHMARKS: dict[ClauseType, dict] = {
    ClauseType.INDEMNIFICATION: {
        "cap_as_pct_of_deal": {"p25": 10, "median": 15, "p75": 25, "unit": "%"},
        "basket_as_pct_of_deal": {"p25": 0.5, "median": 1.0, "p75": 1.5, "unit": "%"},
        "survival_period_months": {"p25": 18, "median": 24, "p75": 36},
        "fundamental_reps_survival_months": {"p25": 60, "median": 72, "p75": 84},
        "notes": "Indian PE deals typically use separate baskets for fundamental and general reps.",
    },
    ClauseType.NON_COMPETE: {
        "duration_years": {"p25": 2, "median": 3, "p75": 5},
        "geographic_scope": "India-wide standard; global requires additional consideration",
        "notes": "Indian Contract Act S.27 voids restraint of trade. Courts rarely enforce >3 years.",
    },
    ClauseType.EARNOUT: {
        "period_years": {"p25": 1, "median": 2, "p75": 3},
        "as_pct_of_deal": {"p25": 10, "median": 20, "p75": 35, "unit": "%"},
        "notes": "Earnout disputes common in India; clear metrics and Big 4 audit rights recommended.",
    },
    ClauseType.LOCK_IN: {
        "promoter_months": {"p25": 24, "median": 36, "p75": 60},
        "investor_months": {"p25": 12, "median": 18, "p75": 24},
        "notes": "SEBI minimums: 3yr promoter, 1yr investor post-IPO. Pre-IPO deals often longer.",
    },
    ClauseType.ESCROW: {
        "as_pct_of_deal": {"p25": 5, "median": 10, "p75": 15, "unit": "%"},
        "release_period_months": {"p25": 12, "median": 18, "p75": 24},
        "notes": "Escrow agent typically a major Indian bank (SBI, HDFC, ICICI).",
    },
    ClauseType.TERMINATION: {
        "break_fee_pct": {"p25": 1, "median": 2, "p75": 3, "unit": "%"},
        "long_stop_date_months": {"p25": 3, "median": 6, "p75": 9},
        "notes": "Long-stop extensions common due to regulatory approval timelines in India.",
    },
    ClauseType.TAG_ALONG_DRAG_ALONG: {
        "drag_threshold_pct": {"p25": 75, "median": 80, "p75": 90},
        "notes": "Below 75% drag threshold is promoter-unfavorable. Best practice: independent valuation by SEBI-registered merchant banker.",
    },
    ClauseType.RESERVED_MATTERS: {
        "typical_count": {"p25": 15, "median": 20, "p75": 30},
        "materiality_threshold_inr_cr": {"p25": 0.5, "median": 1.0, "p75": 5.0},
        "notes": "Over 30 reserved matters suggests investor overreach. Best practice: materiality threshold of ₹1Cr or 5% of revenue.",
    },
    ClauseType.ANTI_DILUTION: {
        "mechanism": "92% of Indian PE deals use broad-based weighted average",
        "notes": "Full ratchet is investor-aggressive and increasingly uncommon in Indian PE.",
    },
    ClauseType.ROFR_ROFO: {
        "exercise_period_days": {"p25": 30, "median": 45, "p75": 60},
        "notes": "Standard exercise period 30-60 days from notice. Must exclude permitted transfers (family, affiliates).",
    },
    ClauseType.INFORMATION_RIGHTS: {
        "quarterly_reporting_required": True,
        "board_observer_standard": True,
        "notes": "Board nomination rights typically for >10% investors. Audit rights should have reasonable frequency cap.",
    },
    ClauseType.PURCHASE_PRICE: {
        "deferred_pct": {"p25": 0, "median": 10, "p75": 20, "unit": "%"},
        "notes": "FEMA pricing guidelines: floor price for incoming investment based on DCF or NAV (Rule 21, FEMA NDI Rules 2019).",
    },
    ClauseType.MATERIAL_ADVERSE_CHANGE: {
        "standard_carveouts": [
            "general economic conditions",
            "industry-wide changes",
            "changes in applicable law",
            "pandemics/epidemics",
            "natural disasters",
        ],
        "notes": "MAC without carve-outs is investor-unfavorable. Indian courts have not yet developed significant MAC jurisprudence.",
    },
    ClauseType.REPRESENTATIONS_WARRANTIES: {
        "sandbagging": "Pro-sandbagging (investor can claim even if knew of breach) is standard in Indian PE",
        "notes": "Fundamental reps (title, authority, capitalization) should survive indefinitely or match limitation period.",
    },
}


def get_benchmark(clause_type: ClauseType) -> dict | None:
    """Get market benchmark data for a clause type."""
    return INDIA_MARKET_BENCHMARKS.get(clause_type)


def compare_to_benchmark(
    clause_type: ClauseType,
    metric: str,
    value: float,
) -> str:
    """Compare a specific value against the market benchmark.

    Returns a human-readable comparison string like:
    "Your indemnity cap at 5% is below p25 (10%). Market median is 15%."
    """
    benchmark = INDIA_MARKET_BENCHMARKS.get(clause_type)
    if not benchmark:
        return ""

    metric_data = benchmark.get(metric)
    if not metric_data or not isinstance(metric_data, dict):
        return ""

    p25 = metric_data.get("p25")
    median = metric_data.get("median")
    p75 = metric_data.get("p75")
    unit = metric_data.get("unit", "")

    if p25 is None or median is None:
        return ""

    if value < p25:
        return (
            f"Value {value}{unit} is below p25 ({p25}{unit}). "
            f"Market median is {median}{unit}. This is in the bottom quartile."
        )
    elif value < median:
        return (
            f"Value {value}{unit} is between p25 ({p25}{unit}) and median ({median}{unit}). "
            f"Below market median but within range."
        )
    elif value <= p75:
        return (
            f"Value {value}{unit} is between median ({median}{unit}) and p75 ({p75}{unit}). "
            f"Within standard market range."
        )
    else:
        return (
            f"Value {value}{unit} is above p75 ({p75}{unit}). "
            f"Market median is {median}{unit}. This is above market standard."
        )


# Deal-type-specific completeness checklists for missing clause detection
DEAL_TYPE_REQUIRED_CLAUSES: dict[str, dict[str, list[ClauseType]]] = {
    "pe_investment": {
        "must_have": [
            ClauseType.PURCHASE_PRICE,
            ClauseType.REPRESENTATIONS_WARRANTIES,
            ClauseType.ANTI_DILUTION,
            ClauseType.TAG_ALONG_DRAG_ALONG,
            ClauseType.RESERVED_MATTERS,
            ClauseType.ROFR_ROFO,
            ClauseType.INFORMATION_RIGHTS,
            ClauseType.LOCK_IN,
            ClauseType.GOVERNING_LAW,
            ClauseType.DISPUTE_RESOLUTION,
            ClauseType.TERMINATION,
            ClauseType.NEGATIVE_COVENANTS,
            ClauseType.AFFIRMATIVE_COVENANTS,
            ClauseType.CONDITIONS_PRECEDENT,
        ],
        "recommended": [
            ClauseType.EARNOUT,
            ClauseType.ESCROW,
            ClauseType.CONFIDENTIALITY,
            ClauseType.EMPLOYEE_MATTERS,
            ClauseType.NON_COMPETE,
        ],
    },
    "acquisition": {
        "must_have": [
            ClauseType.PURCHASE_PRICE,
            ClauseType.REPRESENTATIONS_WARRANTIES,
            ClauseType.INDEMNIFICATION,
            ClauseType.CONDITIONS_PRECEDENT,
            ClauseType.TERMINATION,
            ClauseType.COVENANTS,
            ClauseType.GOVERNING_LAW,
            ClauseType.DISPUTE_RESOLUTION,
            ClauseType.CLOSING_MECHANICS,
            ClauseType.TAX,
        ],
        "recommended": [
            ClauseType.NON_COMPETE,
            ClauseType.EMPLOYEE_MATTERS,
            ClauseType.INTELLECTUAL_PROPERTY,
            ClauseType.ESCROW,
            ClauseType.MATERIAL_ADVERSE_CHANGE,
            ClauseType.EARNOUT,
        ],
    },
    "merger": {
        "must_have": [
            ClauseType.PURCHASE_PRICE,
            ClauseType.REPRESENTATIONS_WARRANTIES,
            ClauseType.CONDITIONS_PRECEDENT,
            ClauseType.TERMINATION,
            ClauseType.GOVERNING_LAW,
            ClauseType.DISPUTE_RESOLUTION,
        ],
        "recommended": [
            ClauseType.INDEMNIFICATION,
            ClauseType.EMPLOYEE_MATTERS,
            ClauseType.MATERIAL_ADVERSE_CHANGE,
        ],
    },
}


def detect_missing_clauses(
    present_types: set[ClauseType],
    deal_type: str,
) -> list[dict]:
    """Detect clauses that should be present but aren't.

    Returns list of {"clause_type": ..., "severity": "must_have"|"recommended", "rationale": ...}
    """
    checklist = DEAL_TYPE_REQUIRED_CLAUSES.get(deal_type)
    if not checklist:
        # Default to acquisition if unknown
        checklist = DEAL_TYPE_REQUIRED_CLAUSES.get("acquisition", {})

    missing = []

    for ct in checklist.get("must_have", []):
        if ct not in present_types:
            missing.append({
                "clause_type": ct.value,
                "severity": "must_have",
                "rationale": f"{ct.value.replace('_', ' ').title()} is a must-have clause for {deal_type} deals.",
            })

    for ct in checklist.get("recommended", []):
        if ct not in present_types:
            missing.append({
                "clause_type": ct.value,
                "severity": "recommended",
                "rationale": f"{ct.value.replace('_', ' ').title()} is recommended for {deal_type} deals.",
            })

    return missing
