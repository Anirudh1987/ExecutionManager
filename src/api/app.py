"""FastAPI application — REST API for the M&A contract review platform."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import deals, contracts, reviews, team, analytics, precedents, templates
from src.api.routes.ws import router as ws_router, ws_manager
from src.services.store import Store
from src.services.precedent_library import PrecedentLibrary
from src.services.template_library import TemplateLibrary
from src.services.time_tracker import TimeTracker
from src.engine.analyzer import ClauseAnalyzer
from src.engine.router import ReviewRouter
from src.engine.pipeline import ReviewPipeline
from src.engine.cross_clause_analyzer import CrossClauseAnalyzer
from src.engine.advisory import AdvisoryGenerator
from src.engine.exporter import AdvisoryExporter
from src.learning.feedback_loop import FeedbackLoop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared services on startup."""
    # Core services
    store = Store()
    precedent_library = PrecedentLibrary()
    template_library = TemplateLibrary()
    time_tracker = TimeTracker()
    feedback = FeedbackLoop()

    # AI client — auto-detect from environment
    ai_client = None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        import anthropic
        ai_client = anthropic.AsyncAnthropic(api_key=api_key)

    # Engine components
    analyzer = ClauseAnalyzer(
        ai_client=ai_client,
        precedent_library=precedent_library,
    )
    router = ReviewRouter()
    cross_clause = CrossClauseAnalyzer()
    advisory = AdvisoryGenerator(ai_client=ai_client)
    exporter = AdvisoryExporter()

    # Pipeline — orchestrates everything
    pipeline = ReviewPipeline(
        store=store,
        analyzer=analyzer,
        router=router,
        cross_clause_analyzer=cross_clause,
        precedent_library=precedent_library,
        time_tracker=time_tracker,
        ws_manager=ws_manager,
    )

    # Attach to app state
    app.state.store = store
    app.state.pipeline = pipeline
    app.state.advisory = advisory
    app.state.exporter = exporter
    app.state.feedback = feedback
    app.state.precedents = precedent_library
    app.state.templates = template_library
    app.state.time_tracker = time_tracker

    yield


app = FastAPI(
    title="ExecutionManager",
    description="AI-powered M&A contract review with human-in-the-loop workflow",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(deals.router, prefix="/deals", tags=["Deals"])
app.include_router(contracts.router, prefix="/contracts", tags=["Contracts"])
app.include_router(reviews.router, prefix="/reviews", tags=["Reviews"])
app.include_router(team.router, prefix="/team", tags=["Team"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(precedents.router, prefix="/precedents", tags=["Precedents"])
app.include_router(templates.router, prefix="/templates", tags=["Templates"])
app.include_router(ws_router, tags=["WebSocket"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ExecutionManager", "version": "0.2.0"}
