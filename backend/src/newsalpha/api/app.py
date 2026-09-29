"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from newsalpha import __version__
from newsalpha.api.routers import evals, health
from newsalpha.core.config import get_settings


def create_app() -> FastAPI:
    """Build the API app with all routers mounted."""
    app = FastAPI(
        title="NewsAlpha API",
        version=__version__,
        description="LLM signals from company announcements. Research only; no trading.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(evals.router)
    return app


app = create_app()
