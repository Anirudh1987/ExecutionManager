"""Cross-clause pattern detection — finds risks that span multiple clauses.

14 interaction checks covering all major M&A clause relationships.
Each pattern returns an interaction_score (0-1) and evidence excerpts.
"""

from __future__ import annotations

import re

from src.models.contract import Clause, ClauseType
from src.models.review import ClauseReview, CrossClausePattern, DealContext, RiskLevel


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
    # 8 new checks
    {
        "pattern_type": "reps_vs_survival",
        "requires": [ClauseType.REPRESENTATIONS_WARRANTIES, ClauseType.INDEMNIFICATION],
        "title": "Representation survival periods match indemnification terms",
    },
    {
        "pattern_type": "escrow_vs_indemnification",
        "requires": [ClauseType.ESCROW, ClauseType.INDEMNIFICATION],
        "title": "Escrow coverage of indemnification obligations",
    },
    {
        "pattern_type": "closing_vs_conditions",
        "requires": [ClauseType.CLOSING_MECHANICS, ClauseType.CONDITIONS_PRECEDENT],
        "title": "Closing mechanics alignment with conditions precedent",
    },
    {
        "pattern_type": "ip_vs_reps",
        "requires": [ClauseType.INTELLECTUAL_PROPERTY, ClauseType.REPRESENTATIONS_WARRANTIES],
        "title": "IP representations match IP assignment/license terms",
    },
    {
        "pattern_type": "employee_vs_covenants",
        "requires": [ClauseType.EMPLOYEE_MATTERS, ClauseType.NON_COMPETE],
        "title": "Employee protections align with restrictive covenants",
    },
    {
        "pattern_type": "tax_vs_price",
        "requires": [ClauseType.TAX, ClauseType.PURCHASE_PRICE],
        "title": "Tax allocation alignment with purchase price structure",
    },
    {
        "pattern_type": "confidentiality_vs_termination",
        "requires": [ClauseType.CONFIDENTIALITY, ClauseType.TERMINATION],
        "title": "Confidentiality survival after termination",
    },
    {
        "pattern_type": "governing_law_vs_dispute",
        "requires": [ClauseType.GOVERNING_LAW, ClauseType.DISPUTE_RESOLUTION],
        "title": "Governing law consistency with dispute resolution forum",
    },
]


class CrossClauseAnalyzer:
    """Detects risk patterns that emerge from interactions between clauses."""

    def analyze_patterns(
        self,
        clauses: list[Clause],
        clause_reviews: list[ClauseReview],
        deal_context: DealContext | None = None,
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
        issues = []
        evidence = []
        score = 0.0

        if "representation" not in indem_text and "warranty" not in indem_text:
            issues.append("Indemnification clause does not explicitly reference representations and warranties")
            score += 0.3

        has_cap = "shall not exceed" in indem_text or "aggregate liability" in indem_text
        has_fundamental_exception = "fundamental" in indem_text or "uncapped" in indem_text

        if has_cap and not has_fundamental_exception:
            issues.append("Indemnification cap may apply to fundamental representations (should be uncapped)")
            evidence.append(_extract_context(indem_text, "shall not exceed", 80))
            score += 0.4

        has_survival = "survival" in indem_text or "survive" in indem_text
        if not has_survival:
            issues.append("No explicit survival period for indemnification claims tied to representations")
            score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="indemnification_vs_reps",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.CRITICAL if score >= 0.7 else RiskLevel.HIGH,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
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
        evidence = []
        score = 0.0

        if "covenant" not in cond_text and "compliance" not in cond_text:
            issues.append("Conditions precedent do not reference compliance with pre-closing covenants")
            score += 0.4

        cov_has_regulatory = "regulatory" in cov_text or "approval" in cov_text
        cond_has_regulatory = "regulatory" in cond_text or "approval" in cond_text
        if cov_has_regulatory and not cond_has_regulatory:
            issues.append("Covenants mention regulatory obligations but conditions do not require regulatory approval")
            evidence.append(_extract_context(cov_text, "regulatory", 80))
            score += 0.5

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="covenants_vs_conditions",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH if score >= 0.5 else RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
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
        price_amounts = _extract_amounts(" ".join(c.text for c in price))
        fee_amounts = _extract_amounts(" ".join(c.text for c in termination))

        issues = []
        evidence = []
        score = 0.0

        if "break fee" not in term_text and "termination fee" not in term_text:
            issues.append("No break fee or termination fee provision found")
            score += 0.6

        if price_amounts and fee_amounts:
            max_price = max(price_amounts)
            max_fee = max(fee_amounts)
            if max_price > 0:
                ratio = max_fee / max_price
                if ratio < 0.01:
                    issues.append(f"Break fee ({max_fee:,.0f}) appears very low relative to purchase price ({max_price:,.0f}) — below 1%")
                    score += 0.4
                elif ratio > 0.05:
                    issues.append(f"Break fee ({max_fee:,.0f}) appears high relative to purchase price ({max_price:,.0f}) — above 5%")
                    score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="termination_vs_break_fee",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH if "no break fee" in str(issues).lower() else RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
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
        evidence = []
        score = 0.0

        if "material adverse" not in cond_text and "mac" not in cond_text:
            issues.append("Conditions precedent do not reference material adverse change")
            score += 0.5

        carveouts = ["industry", "economy", "market", "pandemic", "law"]
        missing_carveouts = [co for co in carveouts if co not in mac_text]
        if len(missing_carveouts) >= 3:
            issues.append(f"MAC definition may be missing standard carve-outs: {', '.join(missing_carveouts)}")
            score += 0.4

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="mac_vs_conditions",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
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
        evidence = []
        score = 0.0

        duration_match = re.search(r'(\d+)\s*(?:year|yr)', nc_text)
        if duration_match:
            years = int(duration_match.group(1))
            if years > 5:
                issues.append(f"Non-compete duration of {years} years may be unenforceable in many jurisdictions")
                evidence.append(_extract_context(nc_text, duration_match.group(0), 80))
                score += 0.5

        if "worldwide" in nc_text or "global" in nc_text:
            issues.append("Worldwide non-compete scope may be unenforceable")
            score += 0.4

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="noncompete_vs_price",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
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
        evidence = []
        score = 0.0

        protections = ["ordinary course", "past practice", "good faith", "commercially reasonable"]
        has_protection = any(p in earnout_text for p in protections)
        if not has_protection:
            issues.append("Earnout clause lacks operational protections (ordinary course, good faith, etc.)")
            score += 0.5

        if "dispute" not in earnout_text and "audit" not in earnout_text:
            issues.append("No dispute resolution or audit rights for earnout calculation")
            score += 0.4

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="earnout_vs_control",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.CRITICAL,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
            recommendation="Include operational covenants preventing buyer from undermining earnout achievement, plus audit rights and dispute resolution mechanism.",
        )

    # --- 8 new cross-clause checks ---

    def _check_reps_vs_survival(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        reps = [c for c in clauses if c.clause_type == ClauseType.REPRESENTATIONS_WARRANTIES]
        indem = [c for c in clauses if c.clause_type == ClauseType.INDEMNIFICATION]

        if not reps or not indem:
            return None

        indem_text = " ".join(c.text.lower() for c in indem)
        reps_text = " ".join(c.text.lower() for c in reps)
        issues = []
        evidence = []
        score = 0.0

        # Check if fundamental reps have longer survival
        has_fundamental_distinction = (
            "fundamental" in indem_text and
            ("24 month" in indem_text or "36 month" in indem_text or
             "statute of limitation" in indem_text)
        )
        has_general_survival = re.search(r'(\d+)\s*month', indem_text)

        if has_general_survival and not has_fundamental_distinction:
            months = int(has_general_survival.group(1))
            issues.append(f"General survival period of {months} months with no distinction for fundamental representations")
            evidence.append(_extract_context(indem_text, has_general_survival.group(0), 80))
            score += 0.5

        # Check if tax reps have separate survival (should match statute of limitations)
        if "tax" in reps_text and "statute of limitation" not in indem_text:
            issues.append("Tax representations exist but indemnification does not tie survival to statute of limitations")
            score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="reps_vs_survival",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
            recommendation="Fundamental reps (title, authority, tax, environmental) should survive 36-72 months or to statute of limitations. General reps typically survive 12-24 months.",
        )

    def _check_escrow_vs_indemnification(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        escrow = [c for c in clauses if c.clause_type == ClauseType.ESCROW]
        indem = [c for c in clauses if c.clause_type == ClauseType.INDEMNIFICATION]

        if not escrow or not indem:
            return None

        escrow_text = " ".join(c.text.lower() for c in escrow)
        indem_text = " ".join(c.text.lower() for c in indem)
        issues = []
        evidence = []
        score = 0.0

        escrow_amounts = _extract_amounts(" ".join(c.text for c in escrow))
        indem_amounts = _extract_amounts(" ".join(c.text for c in indem))

        if escrow_amounts and indem_amounts:
            max_escrow = max(escrow_amounts)
            max_indem = max(indem_amounts)
            if max_indem > 0 and max_escrow < max_indem * 0.5:
                issues.append(f"Escrow amount ({max_escrow:,.0f}) covers less than 50% of indemnification cap ({max_indem:,.0f})")
                score += 0.5

        # Check escrow release timing vs indemnification survival
        if "release" in escrow_text and "survival" not in escrow_text:
            issues.append("Escrow release mechanism does not reference indemnification survival period")
            score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="escrow_vs_indemnification",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH,
            interaction_score=min(1.0, score),
            evidence=[e for e in evidence if e],
            recommendation="Escrow amount should adequately cover indemnification exposure and release timing should align with survival periods.",
        )

    def _check_closing_vs_conditions(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        closing = [c for c in clauses if c.clause_type == ClauseType.CLOSING_MECHANICS]
        conditions = [c for c in clauses if c.clause_type == ClauseType.CONDITIONS_PRECEDENT]

        if not closing or not conditions:
            return None

        closing_text = " ".join(c.text.lower() for c in closing)
        cond_text = " ".join(c.text.lower() for c in conditions)
        issues = []
        score = 0.0

        # Closing should reference satisfaction of conditions
        if "condition" not in closing_text and "satisfaction" not in closing_text:
            issues.append("Closing mechanics do not explicitly reference satisfaction of conditions precedent")
            score += 0.4

        # Check for bring-down certificate requirement
        if "bring-down" not in closing_text and "bring down" not in closing_text:
            if "representation" in cond_text or "warranty" in cond_text:
                issues.append("No bring-down certificate required at closing despite rep-related conditions")
                score += 0.4

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="closing_vs_conditions",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[],
            recommendation="Closing mechanics should explicitly condition closing on satisfaction of all conditions precedent with appropriate certificates.",
        )

    def _check_ip_vs_reps(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        ip = [c for c in clauses if c.clause_type == ClauseType.INTELLECTUAL_PROPERTY]
        reps = [c for c in clauses if c.clause_type == ClauseType.REPRESENTATIONS_WARRANTIES]

        if not ip or not reps:
            return None

        ip_text = " ".join(c.text.lower() for c in ip)
        reps_text = " ".join(c.text.lower() for c in reps)
        issues = []
        score = 0.0

        # IP transfer provisions should be backed by IP reps
        if "assign" in ip_text or "transfer" in ip_text:
            if "intellectual property" not in reps_text and "patent" not in reps_text:
                issues.append("IP assignment/transfer provisions exist but representations lack IP ownership warranties")
                score += 0.6

        # Check for open-source alignment
        if "open source" in ip_text and "open source" not in reps_text:
            issues.append("IP clause addresses open source but representations do not warrant open-source compliance")
            score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="ip_vs_reps",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.HIGH,
            interaction_score=min(1.0, score),
            evidence=[],
            recommendation="IP assignment provisions should be fully supported by IP ownership representations and open-source compliance warranties.",
        )

    def _check_employee_vs_covenants(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        employee = [c for c in clauses if c.clause_type == ClauseType.EMPLOYEE_MATTERS]
        noncompete = [c for c in clauses if c.clause_type == ClauseType.NON_COMPETE]

        if not employee or not noncompete:
            return None

        emp_text = " ".join(c.text.lower() for c in employee)
        nc_text = " ".join(c.text.lower() for c in noncompete)
        issues = []
        score = 0.0

        # Check if non-solicitation aligns with key employee provisions
        if "key employee" in emp_text or "retention" in emp_text:
            if "non-solicitation" not in nc_text and "non-solicit" not in nc_text:
                issues.append("Key employee/retention provisions exist but no non-solicitation covenant protects them")
                score += 0.5

        # Check if severance triggers conflict with non-compete
        if "severance" in emp_text and "non-compete" in nc_text:
            if "garden leave" not in nc_text and "consideration" not in nc_text:
                issues.append("Non-compete may lack adequate consideration for employees subject to severance provisions")
                score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="employee_vs_covenants",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[],
            recommendation="Ensure non-solicitation covenants protect key employees and that non-compete provisions have adequate consideration.",
        )

    def _check_tax_vs_price(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        tax = [c for c in clauses if c.clause_type == ClauseType.TAX]
        price = [c for c in clauses if c.clause_type == ClauseType.PURCHASE_PRICE]

        if not tax or not price:
            return None

        tax_text = " ".join(c.text.lower() for c in tax)
        price_text = " ".join(c.text.lower() for c in price)
        issues = []
        score = 0.0

        # Transfer tax allocation should be clear
        if "transfer tax" in tax_text:
            if "buyer" not in tax_text and "seller" not in tax_text:
                issues.append("Transfer tax mentioned but allocation between buyer and seller is unclear")
                score += 0.4

        # Purchase price allocation for tax purposes
        if "allocation" not in tax_text and "allocat" not in price_text:
            issues.append("No purchase price allocation for tax purposes specified")
            score += 0.4

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="tax_vs_price",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[],
            recommendation="Ensure purchase price allocation for tax purposes is agreed and transfer tax responsibilities are clearly assigned.",
        )

    def _check_confidentiality_vs_termination(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        conf = [c for c in clauses if c.clause_type == ClauseType.CONFIDENTIALITY]
        term = [c for c in clauses if c.clause_type == ClauseType.TERMINATION]

        if not conf or not term:
            return None

        conf_text = " ".join(c.text.lower() for c in conf)
        term_text = " ".join(c.text.lower() for c in term)
        issues = []
        score = 0.0

        # Confidentiality should survive termination
        if "survive" not in conf_text and "survival" not in conf_text:
            if "terminat" in term_text:
                issues.append("Confidentiality provisions do not explicitly survive termination of the agreement")
                score += 0.5

        # Check if termination mentions return of confidential information
        if "confidential" not in term_text and "return" not in term_text:
            issues.append("Termination provisions do not address return or destruction of confidential information")
            score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="confidentiality_vs_termination",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[],
            recommendation="Ensure confidentiality obligations survive termination and that termination provisions address return/destruction of confidential materials.",
        )

    def _check_governing_law_vs_dispute(
        self, title: str, clauses: list[Clause], reviews: dict
    ) -> CrossClausePattern | None:
        gov = [c for c in clauses if c.clause_type == ClauseType.GOVERNING_LAW]
        dispute = [c for c in clauses if c.clause_type == ClauseType.DISPUTE_RESOLUTION]

        if not gov or not dispute:
            return None

        gov_text = " ".join(c.text.lower() for c in gov)
        dispute_text = " ".join(c.text.lower() for c in dispute)
        issues = []
        score = 0.0

        # Extract jurisdiction names and check consistency
        jurisdictions_gov = _extract_jurisdictions(gov_text)
        jurisdictions_dispute = _extract_jurisdictions(dispute_text)

        if jurisdictions_gov and jurisdictions_dispute:
            if not jurisdictions_gov.intersection(jurisdictions_dispute):
                issues.append(
                    f"Governing law jurisdiction ({', '.join(jurisdictions_gov)}) "
                    f"differs from dispute resolution forum ({', '.join(jurisdictions_dispute)})"
                )
                score += 0.6

        # Arbitration clause should specify governing law of arbitration agreement
        if "arbitration" in dispute_text and "governing law" not in dispute_text:
            issues.append("Arbitration clause does not specify governing law of the arbitration agreement itself")
            score += 0.3

        if not issues:
            return None

        return CrossClausePattern(
            pattern_type="governing_law_vs_dispute",
            title=title,
            description="; ".join(issues),
            clauses_involved=[c.id for c in clauses],
            risk_level=RiskLevel.MEDIUM,
            interaction_score=min(1.0, score),
            evidence=[],
            recommendation="Governing law jurisdiction should be consistent with the dispute resolution forum. Arbitration agreements should specify their own governing law.",
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
                description="Multiple high-risk clauses detected across related clause types. Manual cross-reference review recommended.",
                clauses_involved=[c.id for c in involved],
                risk_level=RiskLevel.MEDIUM,
                interaction_score=0.3,
                evidence=[],
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


def _extract_context(text: str, keyword: str, window: int = 80) -> str:
    """Extract text surrounding a keyword for evidence."""
    idx = text.find(keyword.lower() if text == text.lower() else keyword)
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end = min(len(text), idx + len(keyword) + window)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt = excerpt + "..."
    return excerpt


def _extract_jurisdictions(text: str) -> set[str]:
    """Extract jurisdiction/state names from text."""
    jurisdictions = {
        "delaware", "new york", "california", "texas", "england",
        "singapore", "hong kong", "illinois", "nevada", "florida",
    }
    found = set()
    for j in jurisdictions:
        if j in text:
            found.add(j)
    return found
