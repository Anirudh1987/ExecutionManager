"""Tests for version comparison."""

from src.models.contract import Contract, Clause, ClauseType
from src.engine.version_diff import compare_contracts


def _make_contract(clauses_data, contract_id="v1"):
    contract = Contract(
        id=contract_id,
        deal_id="test-deal",
        filename="test.pdf",
    )
    for title, text, ct in clauses_data:
        contract.clauses.append(Clause(
            contract_id=contract_id,
            clause_type=ct,
            title=title,
            text=text,
            section_reference=title,
        ))
    return contract


class TestVersionDiff:
    def test_identical_contracts(self):
        data = [("Section 1", "Same text", ClauseType.OTHER)]
        old = _make_contract(data, "v1")
        new = _make_contract(data, "v2")

        diff = compare_contracts(old, new)
        assert len(diff.added_clauses) == 0
        assert len(diff.removed_clauses) == 0
        assert len(diff.modified_clauses) == 0
        assert "No changes" in diff.summary

    def test_detects_added_clause(self):
        old = _make_contract([
            ("Section 1", "Original text", ClauseType.OTHER),
        ], "v1")
        new = _make_contract([
            ("Section 1", "Original text", ClauseType.OTHER),
            ("Section 2", "New clause", ClauseType.INDEMNIFICATION),
        ], "v2")

        diff = compare_contracts(old, new)
        assert len(diff.added_clauses) == 1
        assert diff.added_clauses[0].title == "Section 2"

    def test_detects_removed_clause(self):
        old = _make_contract([
            ("Section 1", "Keep this", ClauseType.OTHER),
            ("Section 2", "Remove this", ClauseType.OTHER),
        ], "v1")
        new = _make_contract([
            ("Section 1", "Keep this", ClauseType.OTHER),
        ], "v2")

        diff = compare_contracts(old, new)
        assert len(diff.removed_clauses) == 1

    def test_detects_modified_clause(self):
        old = _make_contract([
            ("Section 1", "Old language here", ClauseType.OTHER),
        ], "v1")
        new = _make_contract([
            ("Section 1", "New revised language here", ClauseType.OTHER),
        ], "v2")

        diff = compare_contracts(old, new)
        assert len(diff.modified_clauses) == 1
        assert "modified" in diff.modified_clauses[0].change_type
        assert diff.modified_clauses[0].unified_diff  # has diff text

    def test_summary_describes_changes(self):
        old = _make_contract([
            ("Sec 1", "A", ClauseType.OTHER),
            ("Sec 2", "B", ClauseType.OTHER),
        ], "v1")
        new = _make_contract([
            ("Sec 1", "A modified", ClauseType.OTHER),
            ("Sec 3", "C new", ClauseType.OTHER),
        ], "v2")

        diff = compare_contracts(old, new)
        assert "added" in diff.summary
        assert "removed" in diff.summary
        assert "modified" in diff.summary
