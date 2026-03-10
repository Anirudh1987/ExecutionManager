"""Tests for the clause template library."""

from src.models.contract import ClauseType
from src.services.template_library import ClauseTemplate, TemplateLibrary, DEFAULT_TEMPLATES


class TestTemplateLibrary:
    def test_has_default_templates(self):
        lib = TemplateLibrary()
        assert lib.total_count >= 6  # we ship 6 defaults

    def test_filter_by_clause_type(self):
        lib = TemplateLibrary()
        indem = lib.get_templates(ClauseType.INDEMNIFICATION)
        assert len(indem) >= 1
        assert all(t.clause_type == ClauseType.INDEMNIFICATION for t in indem)

    def test_crud(self):
        lib = TemplateLibrary()
        initial_count = lib.total_count

        template = ClauseTemplate(
            clause_type=ClauseType.ESCROW,
            name="Standard Escrow",
            text="10% of purchase price held in escrow for 18 months.",
            created_by="alice",
        )
        lib.save_template(template)
        assert lib.total_count == initial_count + 1

        retrieved = lib.get_template(template.id)
        assert retrieved.name == "Standard Escrow"

        lib.delete_template(template.id)
        assert lib.total_count == initial_count

    def test_default_templates_are_marked(self):
        lib = TemplateLibrary()
        defaults = [t for t in lib.get_templates() if t.is_default]
        assert len(defaults) >= 6
