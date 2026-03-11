"""Deal management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

from src.models.deal import Deal, DealStatus
from src.models.review import DealContext

router = APIRouter()


class CreateDealRequest(BaseModel):
    name: str
    client_name: str
    deal_type: str = ""
    deal_value: str = ""
    client_side: str = "investor"  # investor, promoter, buyer, seller
    industry: str = ""
    jurisdiction: str = "india"
    deal_structure: str = ""  # SHA, SPA, APA, merger_scheme
    description: str = ""


@router.post("/", response_model=dict)
async def create_deal(req: CreateDealRequest, request: Request):
    store = request.app.state.store
    deal = Deal(
        name=req.name,
        client_name=req.client_name,
        deal_type=req.deal_type,
        deal_value=req.deal_value,
        client_side=req.client_side,
        industry=req.industry,
        jurisdiction=req.jurisdiction,
        deal_structure=req.deal_structure,
        description=req.description,
    )
    await store.save_deal(deal)
    return {"deal_id": deal.id, "status": deal.status.value}


@router.get("/")
async def list_deals(request: Request):
    store = request.app.state.store
    deals = await store.list_deals()
    return [
        {
            "id": d.id,
            "name": d.name,
            "client_name": d.client_name,
            "status": d.status.value,
            "contract_count": len(d.contract_ids),
        }
        for d in deals
    ]


@router.get("/{deal_id}")
async def get_deal(deal_id: str, request: Request):
    store = request.app.state.store
    deal = await store.get_deal(deal_id)
    return {
        "id": deal.id,
        "name": deal.name,
        "client_name": deal.client_name,
        "status": deal.status.value,
        "deal_type": deal.deal_type,
        "deal_value": deal.deal_value,
        "contract_ids": deal.contract_ids,
        "review_ids": deal.review_ids,
        "executive_summary": deal.executive_summary,
        "key_risks": deal.key_risks,
        "recommendations": deal.recommendations,
    }


@router.post("/{deal_id}/assign-team")
async def assign_team(deal_id: str, request: Request):
    """Assign all active team members to a deal."""
    store = request.app.state.store
    deal = await store.get_deal(deal_id)
    members = await store.list_team_members()
    member_ids = [m.id for m in members if m.is_active]
    await store.assign_team_to_deal(deal_id, member_ids)
    deal.team_member_ids = member_ids
    await store.save_deal(deal)
    return {"deal_id": deal_id, "team_size": len(member_ids)}


@router.post("/{deal_id}/generate-advisory")
async def generate_advisory(deal_id: str, request: Request):
    """Generate client advisory from completed reviews."""
    store = request.app.state.store
    advisory_gen = request.app.state.advisory
    deal = await store.get_deal(deal_id)
    contracts = await store.get_contracts_for_deal(deal_id)
    reviews = await store.get_reviews_for_deal(deal_id)
    # Build DealContext from deal fields
    deal_value = None
    if deal.deal_value:
        try:
            deal_value = float(deal.deal_value.replace("$", "").replace(",", "").replace("₹", ""))
        except ValueError:
            pass
    deal_context = DealContext(
        deal_value=deal_value,
        deal_type=deal.deal_type,
        client_side=deal.client_side,
        jurisdiction=deal.jurisdiction,
        industry=deal.industry,
        deal_structure=deal.deal_structure,
    )
    result = await advisory_gen.generate_advisory(deal, contracts, reviews, deal_context)
    await store.save_deal(deal)
    deal.status = DealStatus.ADVISORY_DRAFTING
    await store.save_deal(deal)
    return result


@router.get("/{deal_id}/export")
async def export_advisory(
    deal_id: str,
    request: Request,
    format: str = Query("markdown", regex="^(markdown|html|docx)$"),
):
    """Export advisory as Markdown, HTML, or Word document."""
    store = request.app.state.store
    advisory_gen = request.app.state.advisory
    exporter = request.app.state.exporter

    deal = await store.get_deal(deal_id)
    contracts = await store.get_contracts_for_deal(deal_id)
    reviews = await store.get_reviews_for_deal(deal_id)

    # Build DealContext
    deal_value = None
    if deal.deal_value:
        try:
            deal_value = float(deal.deal_value.replace("$", "").replace(",", "").replace("₹", ""))
        except ValueError:
            pass
    deal_context = DealContext(
        deal_value=deal_value,
        deal_type=deal.deal_type,
        client_side=deal.client_side,
        jurisdiction=deal.jurisdiction,
        industry=deal.industry,
        deal_structure=deal.deal_structure,
    )

    advisory_data = await advisory_gen.generate_advisory(deal, contracts, reviews, deal_context)

    if format == "docx":
        from src.engine.docx_exporter import export_advisory_docx
        docx_bytes = export_advisory_docx(deal, advisory_data, contracts, deal_context)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{deal.name}_advisory.docx"'},
        )
    elif format == "html":
        content = exporter.export_html(deal, advisory_data)
        return HTMLResponse(content=content)
    else:
        content = exporter.export_markdown(deal, advisory_data)
        return PlainTextResponse(content=content)


@router.get("/{deal_id}/negotiation-history")
async def get_negotiation_history(deal_id: str, request: Request):
    """Get negotiation round history for a deal."""
    store = request.app.state.store
    deal = await store.get_deal(deal_id)

    # Gather all reviews and their contract versions
    rounds = []
    for i, review_id in enumerate(deal.review_ids):
        review = await store.get_review(review_id)
        if review:
            contract = await store.get_contract(review.contract_id)
            round_info = {
                "round_number": i + 1,
                "review_id": review.id,
                "contract_id": review.contract_id,
                "contract_title": contract.title if contract else "",
                "clauses_reviewed": len(review.clause_reviews),
                "critical_findings": review.critical_findings_count,
                "progress": review.progress,
                "started_at": review.created_at.isoformat() if review.created_at else None,
                "completed_at": review.completed_at.isoformat() if review.completed_at else None,
            }
            rounds.append(round_info)

    return {"deal_id": deal_id, "total_rounds": len(rounds), "rounds": rounds}
