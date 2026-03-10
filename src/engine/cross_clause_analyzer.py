"""Cross-clause pattern detection — finds risks that span multiple clauses."""

from __future__ import annotations

import re

from src.models.contract import Clause, ClauseType
from src.models.review import ClauseReview, CrossClausePattern, RiskLevel


# Patterns that check relationships between clause types
CROSS_CLAUSE_CHECKS = [
    {
        "pattern_type": "indemnification_vs_reps",
        "requires": [ClauseType.INDEMNIFICATION, ClauseType.REPRESENTATIONS_WARRANTIES],
        "title": "Indemnification scope vs. Representations & Warranties",
    },
    {
        "pattern_type": "covenants_vs_conditions",
        "requires": [ClauseType.COVENANTS, ClauseType.CONDITIONS_PRECEDENT],
        "title": "Covenants alignment with Conditions Precedent",
    },
    {
        "pattern_type": "termination_vs_break_fee",
        "requires": [ClauseType.TERMINATION, ClauseType.PURCHASE_PRICE],
        "title": "Break fee proportionality to deal value",
    },
    {
        "pattern_type": "mac_vs_conditions",
        "requires": [ClauseType.MATERIAL_ADVERSE_CHANGE, ClauseType.CONDITIONS_PRECEDENT],
        "title": "MAC definition alignment with closing conditions",
    },
    {
        "pattern_type": "noncompete_vs_price",
        "requires": [ClauseType.NON_COMPETE, ClauseType.PURCHASE_PRICE],
        "title": "Non-compete scope proportionality to deal value",
    },
    {
        "pattern_type": "earnout_vs_control",
        "requires": [ClauseType.EARNOUT, ClauseType.COVENANTS],
        "title": "Earnout protections against operational interference",
    },
]


class CrossClauseAnalyzer:
    """Detects risk patterns that emerge from interactions between clauses."""

    def analyze_patterns(
        self,
        clauses: list[Clause],
        clause_reviews: list[ClauseReview],
    ) -> list[CrossClausePattern]:
        """Run all cross-clause checks and return detected patterns."""
        clause_by_type: dict[ClauseType, list[Clause]] = {}
        for c in clauses:
            clause_by_type.setdefault(c.clause_type, []).append(c)

        review_by_clause: dict[str, ClauseReview] = {
            cr.clause_id: cr for cr in clause_reviews
        }

        patterns = []
        for check in CROSS_CLAUSE_CHECKS:
            required_types = check["requires"]
            if all(ct in clause_by_type for ct in required_types):
                involved_clauses = []
                for ct in required_types:
                    involved_clauses.extend(clause_by_type[ct])

                pattern = self._run_check(
                    check["pattern_type"],
                    check["title"],
                    involved_clauses,
                    review_by_clause,
                )
                if pattern:
                    patterns.append(pattern)

        return patterns

    def _run_check(
        self,
        pattern_type: str,
        title: str,
        clauses: list[Clause],
        review_by_clause: dict[str, ClauseReview],
    ) -> CrossClausePattern | None:
        """Dispatch to the specific check logic."""
        method = getattr(self, f"_check_{pattern_type}", None)
        if method:
            return method(title, clauses, review_by_clause)
        return self._generic_check(pattern_type, title, clauses, review_by_clause)

    def _check_indemnification_vs_reps(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        indemnification = [c for c in clauses if c.clause_type == ClauseType.INDEMNIFICATION]
        reps = [c for c in clauses if c.clause_type == ClauseType.REPRESENTATIONS_WARRANTIES]

        if not indemnification or not reps:
            return None

        indem_text = " ".join(c.text.lower() for c in indemnification)
        reps_text = " ".join(c.text.lower() for c in reps)

        issues = []

        # Check if indemnification references representations
        if "representation" not in indem_text and "warranty" not in indem_text:
            issues.append("Indemnification clause does not explicitly reference representations and warranties")

        # Check for cap vs uncapped fundamental reps
        has_cap = "shall not exceed" in indem_text or "aggregate liability" in indem_text
        has_fundamental_exception = "fundamental" in indem_text or "uncapped" in indem_text

        if has_cap and not has_fundamental_exception:
            issues.append("Indemnification cap may apply to fundamental representations (should be uncapped)")

        # Check survival period alignment
        has_survival = "survival" in indem_text or "survive" in indem_text
        if not has_survival:
            issues.append("No explicit survival period for indemnification claims tied to representations")

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="indemnification_vs_reps",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH,
            recommendation="Ensure indemnification explicitly covers all representations, with uncapped liability for fundamental reps and appropriate survival periods.",
        )

    def _check_covenants_vs_conditions(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        covenants = [c for c in clauses if c.clause_type == ClauseType.COVENANTS]
        conditions = [c for c in clauses if c.clause_type == ClauseType.CONDITIONS_PRECEDENT]

        if not covenants or not conditions:
            return None

        cov_text = " ".join(c.text.lower() for c in covenants)
        cond_text = " ".join(c.text.lower() for c in conditions)

        issues = []

        # Check if conditions reference compliance with covenants
        if "covenant" not in cond_text and "compliance" not in cond_text:
            issues.append("Conditions precedent do not reference compliance with pre-closing covenants")

        # Check for regulatory approval in both
        cov_has_regulatory = "regulatory" in cov_text or "approval" in cov_text
        cond_has_regulatory = "regulatory" in cond_text or "approval" in cond_text
        if cov_has_regulatory and not cond_has_regulatory:
            issues.append("Covenants mention regulatory obligations but conditions do not require regulatory approval")

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="covenants_vs_conditions",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            recommendation="Align conditions precedent with pre-closing covenants to ensure all obligations are verifiable at closing.",
        )

    def _check_termination_vs_break_fee(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        termination = [c for c in clauses if c.clause_type == ClauseType.TERMINATION]
        price = [c for c in clauses if c.clause_type == ClauseType.PURCHASE_PRICE]

        if not termination or not price:
            return None

        term_text = " ".join(c.text.lower() for c in termination)

        # Extract monetary values from both
        price_amounts = _extract_amounts(" ".join(c.text for c in price))
        fee_amounts = _extract_amounts(" ".join(c.text for c in termination))

        issues = []

        if "break fee" not in term_text and "termination fee" not in term_text:
            issues.append("No break fee or termination fee provision found")

        if price_amounts and fee_amounts:
            max_price = max(price_amounts)
            max_fee = max(fee_amounts)
            if max_price > 0:
                ratio = max_fee / max_price
                if ratio < 0.01:
                    issues.append(f"Break fee ({max_fee:,.0f}) appears very low relative to purchase price ({max_price:,.0f}) — below 1%")
                elif ratio > 0.05:
                    issues.append(f"Break fee ({max_fee:,.0f}) appears high relative to purchase price ({max_price:,.0f}) — above 5%")

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="termination_vs_break_fee",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH if "no break fee" in str(issues).lower() else RiskLevel.MEDIUM,
            recommendation="Break fees in M&A typically range from 2-4% of deal value. Ensure the fee is proportional and covers deal costs.",
        )

    def _check_mac_vs_conditions(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        mac = [c for c in clauses if c.clause_type == ClauseType.MATERIAL_ADVERSE_CHANGE]
        conditions = [c for c in clauses if c.clause_type == ClauseType.CONDITIONS_PRECEDENT]

        if not mac or not conditions:
            return None

        mac_text = " ".join(c.text.lower() for c in mac)
        cond_text = " ".join(c.text.lower() for c in conditions)

        issues = []

        if "material adverse" not in cond_text and "mac" not in cond_text:
            issues.append("Conditions precedent do not reference material adverse change")

        # Check if MAC has standard carve-outs
        carveouts = ["industry", "economy", "market", "pandemic", "law"]
        missing_carveouts = [co for co in carveouts if co not in mac_text]
        if len(missing_carveouts) >= 3:
            issues.append(f"MAC definition may be missing standard carve-outs: {', '.join(missing_carveouts)}")

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="mac_vs_conditions",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH,
            recommendation="Ensure MAC definition is referenced in closing conditions with appropriate carve-outs for industry-wide and macroeconomic changes.",
        )

    def _check_noncompete_vs_price(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        noncompete = [c for c in clauses if c.clause_type == ClauseType.NON_COMPETE]
        price = [c for c in clauses if c.clause_type == ClauseType.PURCHASE_PRICE]

        if not noncompete or not price:
            return None

        nc_text = " ".join(c.text.lower() for c in noncompete)
        issues = []

        # Check duration
        duration_match = re.search(r'(\d+)\s*(?:year|yr)', nc_text)
        if duration_match:
            years = int(duration_match.group(1))
            if years > 5:
                issues.append(f"Non-compete duration of {years} years may be unenforceable in many jurisdictions")

        # Check geographic scope
        if "worldwide" in nc_text or "global" in nc_text:
            issues.append("Worldwide non-compete scope may be unenforceable")

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="noncompete_vs_price",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            recommendation="Non-compete scope should be proportional to deal value and enforceable in target jurisdictions. Typical range: 2-3 years, specific geography.",
        )

    def _check_earnout_vs_control(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        earnout = [c for c in clauses if c.clause_type == ClauseType.EARNOUT]
        covenants = [c for c in clauses if c.clause_type == ClauseType.COVENANTS]

        if not earnout or not covenants:
            return None

        earnout_text = " ".join(c.text.lower() for c in earnout)
        issues = []

        protections = ["ordinary course", "past practice", "good faith", "commercially reasonable"]
        has_protection = any(p in earnout_text for p in protections)
        if not has_protection:
            issues.append("Earnout clause lacks operational protections (ordinary course, good faith, etc.)")

        if "dispute" not in earnout_text and "audit" not in earnout_text:
            issues.append("No dispute resolution or audit rights for earnout calculation")

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="earnout_vs_control",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.CRITICAL,
            recommendation="Include operational covenants preventing buyer from undermining earnout achievement, plus audit rights and dispute resolution mechanism.",
        )

    def _generic_check(
        self, pattern_type: str, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        """Fallback: flag any pair of high-risk clauses that reference each other."""
        high_risk_ids = {
            cr.clause_id
            for cr in reviews.values()
            if cr.ai_risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)
        }

        involved = [c for c in clauses if c.id in high_risk_ids]
        if len(involved) >= 2:
            return CrossClausePattern(
                pattern_type=pattern_type,
                title=title,
                description=f"Multiple high-risk clauses detected across related clause types. Manual cross-reference review recommended.",
                clauses_involved=[c.id for c in involved],
                risk_level=RiskLevel.MEDIUM,
                recommendation="Review these clauses together to ensure consistency and identify any gaps in protection.",
            )
        return None


def _extract_amounts(text: str) -> list[float]:
    """Extract dollar amounts from text."""
    amounts = []
    for match in re.finditer(r'\$[\d,]+(?:\.\d+)?', text):
        try:
            amount = float(match.group().replace('$', '').replace(',', ''))
            amounts.append(amount)
        except ValueError:
            pass
    return amounts
