"""Frontend routes — serves Jinja2 HTML pages with HTMX interactivity."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=_template_dir)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page — deal list."""
    store = request.app.state.store
    deals = await store.list_deals()
    return templates.TemplateResponse("index.html", {"request": request, "deals": deals})


@router.get("/deal/{deal_id}", response_class=HTMLResponse)
async def deal_view(deal_id: str, request: Request):
    """Deal detail — contracts, reviews, status."""
    store = request.app.state.store
    deal = await store.get_deal(deal_id)
    contracts = await store.get_contracts_for_deal(deal_id)
    reviews = await store.get_reviews_for_deal(deal_id)
    team = await store.get_team_for_deal(deal_id)
    return templates.TemplateResponse("deal.html", {
        "request": request, "deal": deal, "contracts": contracts,
        "reviews": reviews, "team": team,
    })


@router.get("/review/{review_id}", response_class=HTMLResponse)
async def review_view(review_id: str, request: Request):
    """Review dashboard — clause list with risk levels and status."""
    store = request.app.state.store
    review = await store.get_review(review_id)
    contract = await store.get_contract(review.contract_id)
    deal = await store.get_deal(review.deal_id)
    clause_map = {c.id: c for c in contract.clauses}
    return templates.TemplateResponse("review.html", {
        "request": request, "review": review, "contract": contract,
        "deal": deal, "clause_map": clause_map,
    })


@router.get("/review/{review_id}/clause/{clause_review_id}", response_class=HTMLResponse)
async def clause_review_view(review_id: str, clause_review_id: str, request: Request):
    """Clause review detail — findings, verdict form."""
    store = request.app.state.store
    review = await store.get_review(review_id)
    cr = next((cr for cr in review.clause_reviews if cr.id == clause_review_id), None)
    contract = await store.get_contract(review.contract_id)
    clause = next((c for c in contract.clauses if c.id == cr.clause_id), None) if cr else None
    deal = await store.get_deal(review.deal_id)
    return templates.TemplateResponse("clause_review.html", {
        "request": request, "review": review, "clause_review": cr,
        "clause": clause, "deal": deal, "contract": contract,
    })


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})
