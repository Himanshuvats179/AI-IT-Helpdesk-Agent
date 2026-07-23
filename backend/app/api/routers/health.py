"""Liveness / readiness / config endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    retriever = getattr(request.app.state, "retriever", None)
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "llm_configured": settings.llm_configured,
        "kb_articles_indexed": retriever.size if retriever else 0,
        "model": settings.llm_model,
    }


@router.get("/v1/config")
async def config() -> dict:
    """Non-secret config the frontend can use (thresholds, demo hints)."""
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "model": settings.llm_model,
        "llm_configured": settings.llm_configured,
        "confidence_auto_threshold": settings.confidence_auto_threshold,
        "confidence_verify_threshold": settings.confidence_verify_threshold,
        "followup_delay_seconds": settings.followup_delay_seconds,
        "otp_demo_enabled": settings.otp_demo_code is not None,
    }
