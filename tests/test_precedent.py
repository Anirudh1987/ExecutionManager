"""Tests for the precedent library."""

from src.models.contract import ClauseType
from src.services.precedent_library import PrecedentEntry, PrecedentLibrary


class TestPrecedentLibrary:
    def test_save_and_find(self):
        lib = PrecedentLibrary()
        entry = PrecedentEntry(
            clause_type=ClauseType.INDEMNIFICATION,
            finding_category="cap_analysis",
            original_text="Liability shall not exceed $5M",
            revised_text="Liability shall not exceed 15% of Purchase Price",
            reviewer_id="alice",
            deal_id="deal-1",
        )
        lib.save_precedent(entry)

        results = lib.find_precedents(ClauseType.INDEMNIFICATION)
        assert len(results) == 1
        assert results[0].revised_text == "Liability shall not exceed 15% of Purchase Price"

    def test_keyword_search(self):
        lib = PrecedentLibrary()
        lib.save_precedent(PrecedentEntry(
            clause_type=ClauseType.INDEMNIFICATION,
            finding_category="cap_analysis",
            original_text="cap at $5M",
            revised_text="cap at 15% of purchase price",
            reviewer_id="alice",
            deal_id="deal-1",
        ))
        lib.save_precedent(PrecedentEntry(
            clause_type=ClauseType.INDEMNIFICATION,
            finding_category="basket_type",
            original_text="deductible basket",
            revised_text="tipping basket with $100k threshold",
            reviewer_id="bob",
            deal_id="deal-2",
        ))

        # Search for "cap"
        results = lib.find_precedents(ClauseType.INDEMNIFICATION, keywords=["cap"])
        assert len(results) == 1
        assert "15%" in results[0].revised_text

    def test_no_results_wrong_type(self):
        lib = PrecedentLibrary()
        lib.save_precedent(PrecedentEntry(
            clause_type=ClauseType.INDEMNIFICATION,
            finding_category="test",
            original_text="test",
            revised_text="test",
            reviewer_id="x",
            deal_id="d",
        ))
        results = lib.find_precedents(ClauseType.TERMINATION)
        assert len(results) == 0

    def test_stats(self):
        lib = PrecedentLibrary()
        lib.save_precedent(PrecedentEntry(
            clause_type=ClauseType.INDEMNIFICATION,
            finding_category="a", original_text="x", revised_text="y",
            reviewer_id="r", deal_id="d",
        ))
        lib.save_precedent(PrecedentEntry(
            clause_type=ClauseType.INDEMNIFICATION,
            finding_category="b", original_text="x", revised_text="y",
            reviewer_id="r", deal_id="d",
        ))
        lib.save_precedent(PrecedentEntry(
            clause_type=ClauseType.TERMINATION,
            finding_category="c", original_text="x", revised_text="y",
            reviewer_id="r", deal_id="d",
        ))

        stats = lib.stats()
        assert stats["indemnification"] == 2
        assert stats["termination"] == 1
        assert lib.total_count == 3
