"""Clause template library — gold-standard clause language for M&A contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.models.contract import ClauseType


class ClauseTemplate(BaseModel):
    """A reusable template for a specific clause type."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    clause_type: ClauseType
    name: str
    text: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    created_by: str = ""
    is_default: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Pre-loaded gold-standard templates
DEFAULT_TEMPLATES = [
    ClauseTemplate(
        clause_type=ClauseType.INDEMNIFICATION,
        name="Standard Indemnification (Buyer-Friendly)",
        text=(
            "Seller shall indemnify, defend, and hold harmless Buyer and its affiliates, "
            "officers, directors, employees, and agents from and against any and all losses, "
            "damages, liabilities, costs, and expenses (including reasonable attorneys' fees) "
            "arising out of or relating to any breach of any representation, warranty, covenant, "
            "or agreement of Seller. The aggregate liability shall not exceed [X]% of the "
            "Purchase Price for general representations and shall be uncapped for fundamental "
            "representations, fraud, and willful breach."
        ),
        description="Buyer-favorable indemnification with uncapped liability for fundamental reps",
        tags=["buyer-friendly", "uncapped-fundamental", "standard"],
        is_default=True,
    ),
    ClauseTemplate(
        clause_type=ClauseType.REPRESENTATIONS_WARRANTIES,
        name="Standard Financial Statements Rep",
        text=(
            "The Financial Statements (i) have been prepared in accordance with GAAP applied "
            "on a consistent basis throughout the periods covered thereby, (ii) fairly present "
            "in all material respects the financial condition and results of operations of the "
            "Company as of the dates and for the periods indicated, and (iii) are consistent "
            "with the books and records of the Company."
        ),
        description="Standard financial statements representation with GAAP compliance",
        tags=["financial", "gaap", "standard"],
        is_default=True,
    ),
    ClauseTemplate(
        clause_type=ClauseType.MATERIAL_ADVERSE_CHANGE,
        name="Balanced MAC Definition",
        text=(
            "\"Material Adverse Change\" means any change, event, occurrence, or development "
            "that, individually or in the aggregate, has had or would reasonably be expected to "
            "have a material adverse effect on the business, assets, financial condition, or "
            "results of operations of the Company, excluding any change arising from: "
            "(a) general economic or market conditions, (b) changes affecting the industry "
            "generally, (c) changes in applicable law or GAAP, (d) acts of war, terrorism, "
            "or natural disasters, (e) pandemics or public health emergencies, or "
            "(f) the announcement or pendency of the transactions contemplated hereby."
        ),
        description="Balanced MAC with standard market carve-outs",
        tags=["balanced", "standard-carveouts"],
        is_default=True,
    ),
    ClauseTemplate(
        clause_type=ClauseType.NON_COMPETE,
        name="Standard Non-Compete (2 Year)",
        text=(
            "For a period of two (2) years following the Closing Date, Seller shall not, "
            "directly or indirectly, engage in, own, manage, operate, or control any business "
            "that competes with the Business within the Territory. This restriction shall not "
            "apply to passive ownership of less than 5% of the outstanding securities of any "
            "publicly traded company."
        ),
        description="Two-year non-compete with passive investment carve-out",
        tags=["2-year", "standard", "passive-carveout"],
        is_default=True,
    ),
    ClauseTemplate(
        clause_type=ClauseType.TERMINATION,
        name="Standard Termination with Break Fee",
        text=(
            "This Agreement may be terminated at any time prior to the Closing: "
            "(a) by mutual written consent; (b) by either party if the Closing has not "
            "occurred by the Outside Date; (c) by either party if a final, non-appealable "
            "order permanently restraining the transactions is issued; (d) by the non-breaching "
            "party upon material breach that is not cured within thirty (30) days. Upon "
            "termination by Seller under clause (d), Buyer shall pay a break fee equal to "
            "[3]% of the Purchase Price."
        ),
        description="Standard termination provisions with 3% break fee",
        tags=["break-fee", "standard", "30-day-cure"],
        is_default=True,
    ),
    ClauseTemplate(
        clause_type=ClauseType.EARNOUT,
        name="Revenue-Based Earnout with Protections",
        text=(
            "Buyer shall pay Seller additional consideration of up to $[X] based on the "
            "Company achieving the following revenue targets during the Earnout Period: "
            "[targets]. Buyer shall operate the Business in the ordinary course consistent "
            "with past practice and shall not take any action with the primary purpose of "
            "reducing the Earnout Payment. Seller shall have the right to review the "
            "calculation of the Earnout Payment and to dispute any calculation within "
            "thirty (30) days of receipt."
        ),
        description="Revenue earnout with anti-manipulation protections",
        tags=["revenue", "anti-manipulation", "dispute-rights"],
        is_default=True,
    ),
]


class TemplateLibrary:
    """Manages clause templates for the review team."""

    def __init__(self):
        self._templates: dict[str, ClauseTemplate] = {}
        for t in DEFAULT_TEMPLATES:
            self._templates[t.id] = t

    def save_template(self, template: ClauseTemplate) -> None:
        self._templates[template.id] = template

    def get_template(self, template_id: str) -> ClauseTemplate:
        template = self._templates.get(template_id)
        if not template:
            raise KeyError(f"Template {template_id} not found")
        return template

    def get_templates(
        self, clause_type: ClauseType | None = None
    ) -> list[ClauseTemplate]:
        templates = list(self._templates.values())
        if clause_type:
            templates = [t for t in templates if t.clause_type == clause_type]
        return templates

    def delete_template(self, template_id: str) -> None:
        if template_id in self._templates:
            del self._templates[template_id]

    @property
    def total_count(self) -> int:
        return len(self._templates)
