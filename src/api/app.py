"""FastAPI application — REST API for the M&A contract review platform.

Supports two storage backends:
- In-memory (default, for testing): USE_SQLITE=0
- SQLite (production): USE_SQLITE=1

AI integration activates when ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import auth, deals, contracts, reviews, team, analytics, precedents, templates, frontend
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
from src.engine.practical_risk_filter import PracticalRiskFilter
from src.engine.time_estimator import TimeEstimator
from src.engine.ai_agents import AIAgentOrchestrator
from src.learning.feedback_loop import FeedbackLoop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared services on startup."""
    # Core services — choose storage backend
    sqlite_store = None
    use_sqlite = os.environ.get("USE_SQLITE", "0") == "1"
    if use_sqlite:
        from src.services.sqlite_store import SqliteStore
        db_path = os.environ.get("DB_PATH", "executionmanager.db")
        sqlite_store = SqliteStore(db_path=db_path)
        await sqlite_store.init_db()
        store = sqlite_store
    else:
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
    risk_filter = PracticalRiskFilter()
    time_estimator = TimeEstimator()
    ai_orchestrator = AIAgentOrchestrator(ai_client=ai_client)

    # Pipeline — orchestrates everything
    pipeline = ReviewPipeline(
        store=store,
        analyzer=analyzer,
        router=router,
        cross_clause_analyzer=cross_clause,
        precedent_library=precedent_library,
        time_tracker=time_tracker,
        risk_filter=risk_filter,
        time_estimator=time_estimator,
        ai_orchestrator=ai_orchestrator,
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
    app.state.ai_orchestrator = ai_orchestrator
    app.state.ai_client = ai_client

    yield

    # Cleanup
    if sqlite_store:
        await sqlite_store.close()


app = FastAPI(
    title="ExecutionManager",
    description="AI-powered M&A contract review with human-in-the-loop workflow",
    version="0.3.0",
    lifespan=lifespan,
)

# Static files for frontend
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(deals.router, prefix="/deals", tags=["Deals"])
app.include_router(contracts.router, prefix="/contracts", tags=["Contracts"])
app.include_router(reviews.router, prefix="/reviews", tags=["Reviews"])
app.include_router(team.router, prefix="/team", tags=["Team"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(precedents.router, prefix="/precedents", tags=["Precedents"])
app.include_router(templates.router, prefix="/templates", tags=["Templates"])
app.include_router(ws_router, tags=["WebSocket"])
app.include_router(frontend.router, prefix="/app", tags=["Frontend"])


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to the web dashboard."""
    return RedirectResponse(url="/app")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ExecutionManager", "version": "0.3.0"}
