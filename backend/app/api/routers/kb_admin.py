"""Knowledge-base admin: list, upsert, reindex, and debug search."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_retriever, get_session
from app.repositories.kb_repository import KBRepository
from app.schemas.kb import KBArticleIn, KBArticleRead, RetrievalResult
from app.services.kb_service import KBService
from app.services.retrieval.retriever import HybridRetriever

router = APIRouter(prefix="/v1/admin/kb", tags=["kb-admin"])


@router.get("", response_model=list[KBArticleRead])
async def list_articles(
    category: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[KBArticleRead]:
    articles = await KBRepository(session).all(category=category)
    return [KBArticleRead.model_validate(a) for a in articles]


@router.post("", response_model=dict)
async def upsert_articles(
    payload: list[KBArticleIn],
    session: AsyncSession = Depends(get_session),
    retriever: HybridRetriever = Depends(get_retriever),
) -> dict:
    service = KBService(session, retriever)
    count = await service.seed(payload)
    await session.commit()
    return {"upserted": len(payload), "indexed": count}


@router.post("/reindex", response_model=dict)
async def reindex(
    session: AsyncSession = Depends(get_session),
    retriever: HybridRetriever = Depends(get_retriever),
) -> dict:
    service = KBService(session, retriever)
    count = await service.reindex()
    return {"indexed": count}


@router.get("/search", response_model=RetrievalResult)
async def search(
    q: str = Query(..., min_length=1),
    category: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    retriever: HybridRetriever = Depends(get_retriever),
) -> RetrievalResult:
    return await KBService(session, retriever).search(q, category=category)
