"""Contract upload and review initiation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.models.contract import Contract

router = APIRouter()


class UploadContractRequest(BaseModel):
    deal_id: str
    filename: str
    title: str = ""
    contract_type: str = ""
    parties: list[str] = []
    raw_text: str
    page_count: int = 0


@router.post("/upload", response_model=dict)
async def upload_contract(req: UploadContractRequest, request: Request):
    """Upload a contract and kick off the review pipeline."""
    store = request.app.state.store
    pipeline = request.app.state.pipeline

    contract = Contract(
        deal_id=req.deal_id,
        filename=req.filename,
        title=req.title or req.filename,
        contract_type=req.contract_type,
        parties=req.parties,
        raw_text=req.raw_text,
        page_count=req.page_count,
    )
    store.save_contract(contract)

    # Add contract to deal
    deal = store.get_deal(req.deal_id)
    deal.contract_ids.append(contract.id)
    store.save_deal(deal)

    # Start the review pipeline
    review = await pipeline.start_review(contract, deal)

    return {
        "contract_id": contract.id,
        "review_id": review.id,
        "clauses_extracted": len(contract.clauses),
        "critical_findings": review.critical_findings_count,
        "pending_human_reviews": len(review.pending_human_reviews),
        "progress": review.progress,
    }


@router.get("/{contract_id}")
async def get_contract(contract_id: str, request: Request):
    store = request.app.state.store
    contract = store.get_contract(contract_id)
    return {
        "id": contract.id,
        "deal_id": contract.deal_id,
        "filename": contract.filename,
        "title": contract.title,
        "contract_type": contract.contract_type,
        "parties": contract.parties,
        "clause_count": contract.clause_count,
        "clauses": [
            {
                "id": c.id,
                "clause_type": c.clause_type.value,
                "title": c.title,
                "section_reference": c.section_reference,
                "summary": c.summary,
                "key_terms": c.key_terms,
            }
            for c in contract.clauses
        ],
    }
