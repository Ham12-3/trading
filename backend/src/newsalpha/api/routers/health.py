"""Liveness and database connectivity check."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from newsalpha import __version__
from newsalpha.db.session import get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    version: str


@router.get("/health", response_model=HealthResponse)
def health(session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    """Report API liveness and whether Postgres answers a trivial query."""
    try:
        session.execute(text("SELECT 1"))
        database: Literal["ok", "unavailable"] = "ok"
    except SQLAlchemyError:
        database = "unavailable"
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        database=database,
        version=__version__,
    )
