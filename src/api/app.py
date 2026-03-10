"""FastAPI application — REST API for the M&A contract review platform."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import deals, contracts, reviews, team, analytics
from src.services.store import Store
from src.engine.analyzer import ClauseAnalyzer
from src.engine.router import ReviewRouter
from src.engine.pipeline import ReviewPipeline
from src.engine.advisory import AdvisoryGenerator
from src.learning.feedback_loop import FeedbackLoop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared services on startup."""
    store = Store()
    analyzer = ClauseAnalyzer()  # no AI client = rule-based fallback
    router = ReviewRouter()
    pipeline = ReviewPipeline(store, analyzer, router)
    advisory = AdvisoryGenerator()
    feedback = FeedbackLoop()

    app.state.store = store
    app.state.pipeline = pipeline
    app.state.advisory = advisory
    app.state.feedback = feedback

    yield


app = FastAPI(
    title="ExecutionManager",
    description="AI-powered M&A contract review with human-in-the-loop workflow",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(deals.router, prefix="/deals", tags=["Deals"])
app.include_router(contracts.router, prefix="/contracts", tags=["Contracts"])
app.include_router(reviews.router, prefix="/reviews", tags=["Reviews"])
app.include_router(team.router, prefix="/team", tags=["Team"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ExecutionManager"}
