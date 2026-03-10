"""Tests for advisory export (Markdown and HTML)."""

from src.models.deal import Deal
from src.engine.exporter import AdvisoryExporter


def _sample_deal():
    return Deal(
        name="Acme Acquisition",
        client_name="Buyer Corp",
        deal_type="acquisition",
        deal_value="$50,000,000",
    )


def _sample_advisory_data():
    return {
        "executive_summary": "Reviewed 10 clauses. 2 critical, 3 high risk.",
        "key_risks": [
            "[Section 3] Indemnification cap at 10% — below market",
            "[Section 2] Missing fundamental rep for IP ownership",
        ],
        "recommendations": [
            "[Section 3] Increase cap to 20% — Suggested: revise language",
        ],
        "negotiation_points": [
            "[Section 5] Break fee at 2% — market standard is 3%",
        ],
        "deal_breakers": [
            "[Section 3] Fraud excluded from indemnification",
        ],
        "risk_distribution": {
            "critical": 2,
            "high": 3,
            "medium": 3,
            "low": 1,
            "informational": 1,
        },
        "total_clauses_reviewed": 10,
        "human_override_rate": 0.15,
    }


class TestAdvisoryExporter:
    def test_export_markdown(self):
        exporter = AdvisoryExporter()
        deal = _sample_deal()
        data = _sample_advisory_data()

        md = exporter.export_markdown(deal, data)

        assert "# M&A Advisory Report — Acme Acquisition" in md
        assert "Buyer Corp" in md
        assert "CRITICAL" in md
        assert "Indemnification cap" in md
        assert "Deal-Breakers" in md
        assert "Negotiation Points" in md
        assert "ExecutionManager" in md

    def test_export_html(self):
        exporter = AdvisoryExporter()
        deal = _sample_deal()
        data = _sample_advisory_data()

        html = exporter.export_html(deal, data)

        assert "<!DOCTYPE html>" in html
        assert "Acme Acquisition" in html
        assert "Buyer Corp" in html
        assert "CRITICAL" in html
        assert "#dc2626" in html  # critical color
        assert "Deal-Breakers" in html

    def test_export_empty_advisory(self):
        exporter = AdvisoryExporter()
        deal = _sample_deal()
        data = {
            "executive_summary": "No issues found.",
            "key_risks": [],
            "recommendations": [],
            "negotiation_points": [],
            "deal_breakers": [],
            "risk_distribution": {},
            "total_clauses_reviewed": 0,
            "human_override_rate": 0.0,
        }

        md = exporter.export_markdown(deal, data)
        assert "No issues found." in md

        html = exporter.export_html(deal, data)
        assert "No issues found." in html
