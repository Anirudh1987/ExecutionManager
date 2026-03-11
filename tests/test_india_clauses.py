"""Tests for India-specific clause types, risk patterns, and cross-clause checks."""

import pytest

from src.models.contract import Clause, ClauseType
from src.models.review import ClauseReview, DealContext, RiskLevel, ReviewStage
from src.engine.analyzer import ClauseAnalyzer, RISK_PATTERNS
from src.engine.cross_clause_analyzer import CrossClauseAnalyzer, RISK_CASCADE_MAP


class TestIndiaClauseTypes:
    """Verify all 8 new Indian clause types have risk patterns."""

    INDIA_TYPES = [
        ClauseType.ANTI_DILUTION,
        ClauseType.TAG_ALONG_DRAG_ALONG,
        ClauseType.RESERVED_MATTERS,
        ClauseType.ROFR_ROFO,
        ClauseType.LOCK_IN,
        ClauseType.INFORMATION_RIGHTS,
        ClauseType.AFFIRMATIVE_COVENANTS,
        ClauseType.NEGATIVE_COVENANTS,
    ]

    def test_all_india_types_have_patterns(self):
        for ct in self.INDIA_TYPES:
            assert ct in RISK_PATTERNS, f"Missing RISK_PATTERNS for {ct.value}"
            assert len(RISK_PATTERNS[ct]) >= 2, f"Too few patterns for {ct.value}"

    def test_patterns_have_investor_risk(self):
        for ct in self.INDIA_TYPES:
            for pattern in RISK_PATTERNS[ct]:
                assert "investor_risk" in pattern, (
                    f"Pattern '{pattern['category']}' in {ct.value} missing investor_risk"
                )

    def test_patterns_have_promoter_risk(self):
        for ct in self.INDIA_TYPES:
            for pattern in RISK_PATTERNS[ct]:
                assert "promoter_risk" in pattern, (
                    f"Pattern '{pattern['category']}' in {ct.value} missing promoter_risk"
                )

    def test_patterns_have_market_benchmark(self):
        for ct in self.INDIA_TYPES:
            for pattern in RISK_PATTERNS[ct]:
                assert "market_benchmark" in pattern, (
                    f"Pattern '{pattern['category']}' in {ct.value} missing market_benchmark"
                )


class TestInvestorPromoterPerspective:
    """Verify investor/promoter risk levels differ appropriately."""

    def test_investor_perspective(self):
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.ANTI_DILUTION,
            title="Anti-Dilution",
            text="Full ratchet anti-dilution protection",
        )
        context = DealContext(client_side="investor")
        findings = analyzer._rule_based_analyze(clause, context)
        assert len(findings) >= 2
        # Investor risk for full ratchet should be LOW (favorable to investor)
        formula_finding = next(f for f in findings if f.category == "anti_dilution_formula")
        assert formula_finding.risk_level == RiskLevel.LOW

    def test_promoter_perspective(self):
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.ANTI_DILUTION,
            title="Anti-Dilution",
            text="Full ratchet anti-dilution protection",
        )
        context = DealContext(client_side="promoter")
        findings = analyzer._rule_based_analyze(clause, context)
        formula_finding = next(f for f in findings if f.category == "anti_dilution_formula")
        assert formula_finding.risk_level == RiskLevel.CRITICAL

    def test_reserved_matters_investor_vs_promoter(self):
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.RESERVED_MATTERS,
            title="Reserved Matters",
            text="Expansive list of reserved matters",
        )

        investor_findings = analyzer._rule_based_analyze(
            clause, DealContext(client_side="investor")
        )
        promoter_findings = analyzer._rule_based_analyze(
            clause, DealContext(client_side="promoter")
        )

        scope_inv = next(f for f in investor_findings if f.category == "reserved_matters_scope")
        scope_prom = next(f for f in promoter_findings if f.category == "reserved_matters_scope")

        # Investor: low risk (favorable), Promoter: critical risk
        assert scope_inv.risk_level == RiskLevel.LOW
        assert scope_prom.risk_level == RiskLevel.CRITICAL

    def test_market_benchmark_included(self):
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.LOCK_IN,
            title="Lock-In",
            text="3 year lock-in",
        )
        context = DealContext(client_side="investor")
        findings = analyzer._rule_based_analyze(clause, context)
        assert any(f.market_comparison for f in findings)


class TestIndiaCrossClauseChecks:
    """Test the 4 new India-specific cross-clause checks."""

    def _make_clause(self, clause_type, text, clause_id=""):
        return Clause(
            id=clause_id or f"clause_{clause_type.value}",
            contract_id="c1",
            clause_type=clause_type,
            title=clause_type.value,
            text=text,
        )

    def test_rofr_vs_tag_along_detects_conflict(self):
        analyzer = CrossClauseAnalyzer()
        clauses = [
            self._make_clause(ClauseType.ROFR_ROFO, "ROFR with 30 day exercise period"),
            self._make_clause(ClauseType.TAG_ALONG_DRAG_ALONG, "Tag-along with drag-along at 75% threshold. 45 day exercise period."),
        ]
        reviews = {}
        patterns = analyzer.analyze_patterns(clauses, [], DealContext())
        # Should detect ROFR doesn't mention tag-along and drag doesn't mention ROFR
        rofr_pattern = [p for p in patterns if p.pattern_type == "rofr_vs_tag_along"]
        assert len(rofr_pattern) == 1

    def test_reserved_matters_vs_covenants_detects_gap(self):
        analyzer = CrossClauseAnalyzer()
        clauses = [
            self._make_clause(
                ClauseType.RESERVED_MATTERS,
                "Reserved matters include: related party transactions, debt above ₹1Cr",
            ),
            self._make_clause(
                ClauseType.NEGATIVE_COVENANTS,
                "The company shall not incur debt above ₹1Cr",
            ),
        ]
        patterns = analyzer.analyze_patterns(clauses, [], DealContext())
        rpt_pattern = [p for p in patterns if p.pattern_type == "reserved_matters_vs_covenants"]
        assert len(rpt_pattern) == 1

    def test_lock_in_vs_termination_detects_missing_carveout(self):
        analyzer = CrossClauseAnalyzer()
        clauses = [
            self._make_clause(ClauseType.LOCK_IN, "3 year lock-in period for all shareholders"),
            self._make_clause(ClauseType.TERMINATION, "Either party may terminate on 30 days notice"),
        ]
        patterns = analyzer.analyze_patterns(clauses, [], DealContext())
        lock_pattern = [p for p in patterns if p.pattern_type == "lock_in_vs_termination"]
        assert len(lock_pattern) == 1
        assert "breach" in lock_pattern[0].description.lower() or "ipo" in lock_pattern[0].description.lower()

    def test_anti_dilution_vs_price(self):
        analyzer = CrossClauseAnalyzer()
        clauses = [
            self._make_clause(ClauseType.ANTI_DILUTION, "Broad-based weighted average anti-dilution"),
            self._make_clause(ClauseType.PURCHASE_PRICE, "Total consideration of ₹100Cr"),
        ]
        patterns = analyzer.analyze_patterns(clauses, [], DealContext())
        anti_pattern = [p for p in patterns if p.pattern_type == "anti_dilution_vs_price"]
        assert len(anti_pattern) == 1


class TestRiskCascade:
    """Test risk cascade analysis."""

    def test_indemnity_change_cascades(self):
        analyzer = CrossClauseAnalyzer()
        clauses = [
            Clause(
                id="escrow1", contract_id="c1",
                clause_type=ClauseType.ESCROW, title="Escrow", text="Escrow",
            ),
            Clause(
                id="price1", contract_id="c1",
                clause_type=ClauseType.PURCHASE_PRICE, title="Price", text="Price",
            ),
        ]
        warnings = analyzer.analyze_cascade(ClauseType.INDEMNIFICATION, clauses)
        assert len(warnings) >= 2
        affected_types = {w["affected_clause_type"] for w in warnings}
        assert "escrow" in affected_types
        assert "purchase_price" in affected_types

    def test_price_change_cascades_to_anti_dilution(self):
        analyzer = CrossClauseAnalyzer()
        clauses = [
            Clause(
                id="ad1", contract_id="c1",
                clause_type=ClauseType.ANTI_DILUTION, title="Anti-Dilution", text="AD",
            ),
        ]
        warnings = analyzer.analyze_cascade(ClauseType.PURCHASE_PRICE, clauses)
        affected_types = {w["affected_clause_type"] for w in warnings}
        assert "anti_dilution" in affected_types

    def test_no_cascade_for_unrelated(self):
        analyzer = CrossClauseAnalyzer()
        clauses = [
            Clause(
                id="conf1", contract_id="c1",
                clause_type=ClauseType.CONFIDENTIALITY, title="Conf", text="Conf",
            ),
        ]
        # ANTI_DILUTION doesn't cascade to CONFIDENTIALITY
        warnings = analyzer.analyze_cascade(ClauseType.ANTI_DILUTION, clauses)
        affected_types = {w["affected_clause_type"] for w in warnings}
        assert "confidentiality" not in affected_types
