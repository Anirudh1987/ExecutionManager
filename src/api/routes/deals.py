"""Deal management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from src.models.deal import Deal, DealStatus

router = APIRouter()


class CreateDealRequest(BaseModel):
    name: str
    client_name: str
    deal_type: str = ""
    deal_value: str = ""
    description: str = ""


@router.post("/", response_model=dict)
async def create_deal(req: CreateDealRequest, request: Request):
    store = request.app.state.store
    deal = Deal(
        name=req.name,
        client_name=req.client_name,
        deal_type=req.deal_type,
        deal_value=req.deal_value,
        description=req.description,
    )
    store.save_deal(deal)
    return {"deal_id": deal.id, "status": deal.status.value}


@router.get("/")
async def list_deals(request: Request):
    store = request.app.state.store
    deals = store.list_deals()
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
    deal = store.get_deal(deal_id)
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
    deal = store.get_deal(deal_id)
    members = store.list_team_members()
    member_ids = [m.id for m in members if m.is_active]
    store.assign_team_to_deal(deal_id, member_ids)
    deal.team_member_ids = member_ids
    store.save_deal(deal)
    return {"deal_id": deal_id, "team_size": len(member_ids)}


@router.post("/{deal_id}/generate-advisory")
async def generate_advisory(deal_id: str, request: Request):
    """Generate client advisory from completed reviews."""
    store = request.app.state.store
    advisory_gen = request.app.state.advisory
    deal = store.get_deal(deal_id)
    contracts = store.get_contracts_for_deal(deal_id)
    reviews = store.get_reviews_for_deal(deal_id)
    result = await advisory_gen.generate_advisory(deal, contracts, reviews)
    store.save_deal(deal)
    deal.status = DealStatus.ADVISORY_DRAFTING
    store.save_deal(deal)
    return result


@router.get("/{deal_id}/export")
async def export_advisory(
    deal_id: str,
    request: Request,
    format: str = Query("markdown", regex="^(markdown|html)$"),
):
    """Export advisory as Markdown or HTML document."""
    store = request.app.state.store
    advisory_gen = request.app.state.advisory
    exporter = request.app.state.exporter

    deal = store.get_deal(deal_id)
    contracts = store.get_contracts_for_deal(deal_id)
    reviews = store.get_reviews_for_deal(deal_id)
    advisory_data = await advisory_gen.generate_advisory(deal, contracts, reviews)

    if format == "html":
        content = exporter.export_html(deal, advisory_data)
        return HTMLResponse(content=content)
    else:
        content = exporter.export_markdown(deal, advisory_data)
        return PlainTextResponse(content=content)
