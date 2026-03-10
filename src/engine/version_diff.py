"""Version comparison — diffs successive contract drafts at the clause level."""

from __future__ import annotations

import difflib

from src.models.contract import Clause, ClauseDiff, Contract, ContractDiff


def compare_contracts(old: Contract, new: Contract) -> ContractDiff:
    """Compare two contract versions and produce a structured diff.

    Matches clauses by section_reference/title, then diffs the text.
    """
    old_by_ref = {_clause_key(c): c for c in old.clauses}
    new_by_ref = {_clause_key(c): c for c in new.clauses}

    old_keys = set(old_by_ref.keys())
    new_keys = set(new_by_ref.keys())

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    common_keys = old_keys & new_keys

    added = [new_by_ref[k] for k in added_keys]
    removed = [old_by_ref[k] for k in removed_keys]

    modified = []
    for key in common_keys:
        old_clause = old_by_ref[key]
        new_clause = new_by_ref[key]
        if old_clause.text.strip() != new_clause.text.strip():
            diff = _diff_clause(old_clause, new_clause)
            modified.append(diff)

    summary_parts = []
    if added:
        summary_parts.append(f"{len(added)} clause(s) added")
    if removed:
        summary_parts.append(f"{len(removed)} clause(s) removed")
    if modified:
        summary_parts.append(f"{len(modified)} clause(s) modified")
    if not summary_parts:
        summary_parts.append("No changes detected")

    return ContractDiff(
        old_contract_id=old.id,
        new_contract_id=new.id,
        added_clauses=added,
        removed_clauses=removed,
        modified_clauses=modified,
        summary="; ".join(summary_parts),
    )


def _clause_key(clause: Clause) -> str:
    """Key for matching clauses across versions."""
    ref = clause.section_reference.strip().lower()
    title = clause.title.strip().lower()
    return ref or title


def _diff_clause(old: Clause, new: Clause) -> ClauseDiff:
    """Produce a unified diff between two clause versions."""
    old_lines = old.text.splitlines(keepends=True)
    new_lines = new.text.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"v{old.contract_id} — {old.title}",
        tofile=f"v{new.contract_id} — {new.title}",
        lineterm="",
    ))
    unified = "\n".join(diff_lines)

    # Generate a human-readable change summary
    added_count = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
    removed_count = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))

    change_summary = f"{added_count} line(s) added, {removed_count} line(s) removed"

    return ClauseDiff(
        old_title=old.title,
        new_title=new.title,
        old_text=old.text,
        new_text=new.text,
        change_type="modified",
        unified_diff=unified,
        change_summary=change_summary,
    )
