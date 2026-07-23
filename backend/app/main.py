"""FastAPI application factory and lifespan wiring (the composition root).

``create_app`` accepts optional ``provider`` / ``retriever`` overrides and flags
so tests can inject a scripted LLM + in-memory retriever and skip the scheduler,
while production builds the real Claude adapter + ChromaDB retriever.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.routers import health, hitl, kb_admin, messages, stream, tickets, verify
from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import dispose_engine, init_models
from app.db.session import session_scope
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.provider import LLMProvider, UnconfiguredProvider
from app.repositories.kb_repository import KBRepository
from app.seed.seed_kb import load_seed_articles, seed_demo_users
from app.services.kb_service import KBService
from app.services.notification_service import get_event_bus
from app.services.retrieval.factory import build_retriever
from app.services.retrieval.retriever import HybridRetriever
from app.workers.scheduler import SchedulerWorker

logger = get_logger(__name__)


def _make_provider(settings) -> LLMProvider:
    if settings.llm_configured:
        try:
            return AnthropicProvider(settings)
        except Exception as exc:  # noqa: BLE001
            logger.error("provider_init_failed", error=str(exc))
            return UnconfiguredProvider()
    logger.warning("llm_not_configured", hint="Set ANTHROPIC_API_KEY in backend/.env")
    return UnconfiguredProvider()


def create_app(
    *,
    provider: LLMProvider | None = None,
    retriever: HybridRetriever | None = None,
    start_scheduler: bool = True,
    seed: bool = True,
    run_migrations: bool = True,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level, settings.log_json)
        logger.info("starting", app=settings.app_name, env=settings.environment)

        if run_migrations:
            await init_models()

        app.state.retriever = retriever or build_retriever(settings)
        app.state.event_bus = get_event_bus()

        async with session_scope() as session:
            await seed_demo_users(session)
            kb = KBService(session, app.state.retriever)
            existing = await KBRepository(session).all()
            if seed and not existing:
                await kb.seed(load_seed_articles())
            else:
                await kb.reindex()
            await session.commit()

        app.state.provider = provider or _make_provider(settings)
        from app.agent.runner import AgentRunner

        app.state.runner = AgentRunner(
            app.state.provider, app.state.retriever,
            event_bus=app.state.event_bus, settings=settings,
        )

        app.state.scheduler = None
        if start_scheduler:
            app.state.scheduler = SchedulerWorker(app.state.runner, settings)
            app.state.scheduler.start()

        try:
            yield
        finally:
            if app.state.scheduler is not None:
                await app.state.scheduler.stop()
            await dispose_engine()

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    for module in (health, tickets, messages, verify, hitl, kb_admin, stream):
        app.include_router(module.router)

    return app


app = create_app()


if __name__ == "__main__":
    import os

    import uvicorn

    # Default to loopback; opt into 0.0.0.0 explicitly for container deployments.
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = get_settings().environment == "development"
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)
