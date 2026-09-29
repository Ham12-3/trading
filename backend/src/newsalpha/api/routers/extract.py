"""On-demand extraction for one announcement (default model and prompt)."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from newsalpha.api.deps import (
    SignalSource,
    data_dir,
    default_signal_source,
    get_provider,
    models_config,
)
from newsalpha.api.schemas import SignalOut
from newsalpha.db.models import Announcement, Signal
from newsalpha.db.session import get_session
from newsalpha.extraction.prompts import load_prompt
from newsalpha.extraction.providers import LLMProvider
from newsalpha.extraction.runner import PromptChangedError, run_extraction

router = APIRouter(tags=["extraction"])


@router.post("/extract/{announcement_id}", response_model=SignalOut)
def extract_one(
    announcement_id: int,
    session: Annotated[Session, Depends(get_session)],
    source: Annotated[SignalSource, Depends(default_signal_source)],
    provider: Annotated[LLMProvider, Depends(get_provider)],
    base_dir: Annotated[Path, Depends(data_dir)],
) -> SignalOut:
    """Extract signals unless an ok result already exists (never pays twice for one document).

    A previously failed extraction is retried.
    """
    if session.get(Announcement, announcement_id) is None:
        raise HTTPException(status_code=404, detail="announcement not found")
    cfg = models_config()
    try:
        run_extraction(
            session=session,
            provider=provider,
            model=source.model,
            prompt=load_prompt(source.prompt_version),
            price=cfg.price(source.model),
            settings=cfg.extraction,
            data_dir=base_dir,
            retry_failed=True,
            announcement_ids=[announcement_id],
        )
    except PromptChangedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    signal = session.scalar(
        select(Signal).where(
            Signal.announcement_id == announcement_id,
            Signal.model == source.model,
            Signal.prompt_version == source.prompt_version,
        )
    )
    if signal is None:  # pragma: no cover - run_extraction always writes a row
        raise HTTPException(status_code=500, detail="extraction produced no row")
    return SignalOut.model_validate(signal, from_attributes=True)
