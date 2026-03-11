"""Tests for market benchmarks and missing clause detection."""

import pytest

from src.models.contract import ClauseType
from src.engine.market_benchmarks import (
    INDIA_MARKET_BENCHMARKS,
    DEAL_TYPE_REQUIRED_CLAUSES,
    get_benchmark,
    compare_to_benchmark,
    detect_missing_clauses,
)


class TestBenchmarks:
    def test_benchmarks_have_notes(self):
        for key, data in INDIA_MARKET_BENCHMARKS.items():
            assert "notes" in data, f"Missing 'notes' in {key}"

    def test_benchmarks_cover_key_types(self):
        key_types = [
            ClauseType.INDEMNIFICATION,
            ClauseType.NON_COMPETE,
            ClauseType.LOCK_IN,
            ClauseType.ANTI_DILUTION,
            ClauseType.TAG_ALONG_DRAG_ALONG,
            ClauseType.RESERVED_MATTERS,
        ]
        for ct in key_types:
            assert ct in INDIA_MARKET_BENCHMARKS, f"Missing benchmarks for {ct.value}"

    def test_get_benchmark(self):
        result = get_benchmark(ClauseType.INDEMNIFICATION)
        assert result is not None
        assert "cap_as_pct_of_deal" in result

    def test_get_benchmark_missing(self):
        result = get_benchmark(ClauseType.OTHER)
        assert result is None

    def test_compare_below_p25(self):
        result = compare_to_benchmark(ClauseType.INDEMNIFICATION, "cap_as_pct_of_deal", 5)
        assert "below p25" in result

    def test_compare_at_median(self):
        result = compare_to_benchmark(ClauseType.INDEMNIFICATION, "cap_as_pct_of_deal", 15)
        assert "median" in result

    def test_compare_above_p75(self):
        result = compare_to_benchmark(ClauseType.INDEMNIFICATION, "cap_as_pct_of_deal", 50)
        assert "above p75" in result

    def test_compare_invalid_type(self):
        result = compare_to_benchmark(ClauseType.OTHER, "cap", 10)
        assert result == ""

    def test_compare_invalid_metric(self):
        result = compare_to_benchmark(ClauseType.INDEMNIFICATION, "nonexistent_metric", 10)
        assert result == ""


class TestMissingClauses:
    def test_pe_investment_missing_clauses(self):
        present = {ClauseType.PURCHASE_PRICE, ClauseType.REPRESENTATIONS_WARRANTIES}
        missing = detect_missing_clauses(present, "pe_investment")
        assert len(missing) > 0
        missing_types = {m["clause_type"] for m in missing}
        assert "anti_dilution" in missing_types
        assert "reserved_matters" in missing_types

    def test_pe_investment_complete(self):
        """If all required clauses present, nothing should be missing."""
        required = DEAL_TYPE_REQUIRED_CLAUSES.get("pe_investment", {})
        present = set()
        for importance, types in required.items():
            for t in types:
                present.add(t)
        missing = detect_missing_clauses(present, "pe_investment")
        assert len(missing) == 0

    def test_acquisition_missing_clauses(self):
        present = {ClauseType.PURCHASE_PRICE}
        missing = detect_missing_clauses(present, "acquisition")
        assert len(missing) > 0
        missing_types = {m["clause_type"] for m in missing}
        assert "indemnification" in missing_types

    def test_unknown_deal_type_uses_default(self):
        """Unknown deal type falls back to acquisition checklist."""
        missing = detect_missing_clauses(set(), "unknown_type")
        # Falls back to acquisition which has must-have items
        assert len(missing) > 0

    def test_missing_clauses_have_severity(self):
        present = set()
        missing = detect_missing_clauses(present, "pe_investment")
        for m in missing:
            assert "severity" in m
            assert m["severity"] in ("must_have", "recommended")
