"""Contract upload and review initiation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel

from src.models.contract import Contract
from src.engine.pdf_parser import extract_text_from_pdf
from src.engine.version_diff import compare_contracts

router = APIRouter()


class UploadContractRequest(BaseModel):
    deal_id: str
    filename: str
    title: str = ""
    contract_type: str = ""
    parties: list[str] = []
    raw_text: str
    page_count: int = 0
    previous_version_id: str = ""  # For negotiation round tracking


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
        previous_version_id=req.previous_version_id or None,
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


@router.post("/upload-pdf", response_model=dict)
async def upload_pdf(
    request: Request,
    deal_id: str = Form(...),
    title: str = Form(""),
    contract_type: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload a PDF contract, extract text, and start the review pipeline."""
    store = request.app.state.store
    pipeline = request.app.state.pipeline

    pdf_bytes = await file.read()
    raw_text, page_count = extract_text_from_pdf(pdf_bytes)

    contract = Contract(
        deal_id=deal_id,
        filename=file.filename or "uploaded.pdf",
        title=title or file.filename or "Untitled",
        contract_type=contract_type,
        raw_text=raw_text,
        page_count=page_count,
    )
    store.save_contract(contract)

    deal = store.get_deal(deal_id)
    deal.contract_ids.append(contract.id)
    store.save_deal(deal)

    review = await pipeline.start_review(contract, deal)

    return {
        "contract_id": contract.id,
        "review_id": review.id,
        "pages_extracted": page_count,
        "clauses_extracted": len(contract.clauses),
        "critical_findings": review.critical_findings_count,
        "pending_human_reviews": len(review.pending_human_reviews),
        "progress": review.progress,
    }


@router.get("/{contract_id}/compare/{other_contract_id}")
async def compare_contract_versions(
    contract_id: str, other_contract_id: str, request: Request
):
    """Compare two contract versions and return a structured diff."""
    store = request.app.state.store
    old = store.get_contract(contract_id)
    new = store.get_contract(other_contract_id)
    diff = compare_contracts(old, new)
    return {
        "old_contract_id": diff.old_contract_id,
        "new_contract_id": diff.new_contract_id,
        "summary": diff.summary,
        "added_count": len(diff.added_clauses),
        "removed_count": len(diff.removed_clauses),
        "modified_count": len(diff.modified_clauses),
        "added_clauses": [
            {"title": c.title, "clause_type": c.clause_type.value}
            for c in diff.added_clauses
        ],
        "removed_clauses": [
            {"title": c.title, "clause_type": c.clause_type.value}
            for c in diff.removed_clauses
        ],
        "modified_clauses": [
            {
                "old_title": m.old_title,
                "new_title": m.new_title,
                "change_summary": m.change_summary,
                "unified_diff": m.unified_diff,
            }
            for m in diff.modified_clauses
        ],
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


@router.get("/{contract_id}/redline")
async def export_redline(
    contract_id: str,
    request: Request,
    review_id: str = Query(...),
):
    """Export a redlined Word document for a contract review."""
    store = request.app.state.store
    contract = store.get_contract(contract_id)
    review = store.get_review(review_id)

    from src.engine.docx_exporter import export_redline_docx

    # Determine negotiation round
    deal = store.get_deal(contract.deal_id)
    round_num = 1
    if deal:
        for i, rid in enumerate(deal.review_ids):
            if rid == review_id:
                round_num = i + 1
                break

    docx_bytes = export_redline_docx(
        contract, review, negotiation_round=round_num
    )
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{contract.filename}_redline.docx"'},
    )
