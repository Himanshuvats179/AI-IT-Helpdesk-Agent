"""Shared test fixtures.

Each test gets an isolated temp SQLite DB, an offline in-memory retriever
(hashing embedder + in-memory vector store), seeded KB + demo users, and a
scripted FakeLLM injected via DI. No network, no model downloads.
"""
from __future__ import annotations

import os

# Configure environment BEFORE importing app.config (settings are cached).
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OTP_DEMO_CODE"] = "123456"
os.environ["FOLLOWUP_DELAY_SECONDS"] = "1"
os.environ["FOLLOWUP_NO_RESPONSE_TIMEOUT_SECONDS"] = "1"
os.environ["SCHEDULER_POLL_SECONDS"] = "1"
os.environ["APPROVAL_TIMEOUT_SECONDS"] = "1"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.base import dispose_engine, init_models  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.services.retrieval.embedder import DeterministicHashEmbedder  # noqa: E402
from app.services.retrieval.retriever import HybridRetriever  # noqa: E402
from app.services.retrieval.vector_store import InMemoryVectorStore  # noqa: E402


def make_retriever() -> HybridRetriever:
    return HybridRetriever(
        DeterministicHashEmbedder(),
        InMemoryVectorStore(),
        top_k=4,
        dense_k=20,
        keyword_k=20,
        score_floor=0.30,
    )


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    get_settings.cache_clear()
    await dispose_engine()
    await init_models()
    try:
        yield
    finally:
        await dispose_engine()
        get_settings.cache_clear()


@pytest.fixture
def settings(db):
    return get_settings()


@pytest_asyncio.fixture
async def retriever(db):
    return make_retriever()


@pytest_asyncio.fixture
async def seeded(retriever):
    """Seed demo users + KB into the temp DB and index it."""
    from app.seed.seed_kb import load_seed_articles, seed_demo_users
    from app.services.kb_service import KBService

    async with session_scope() as session:
        await seed_demo_users(session)
        await KBService(session, retriever).seed(load_seed_articles())
        await session.commit()
    return retriever


@pytest.fixture
def make_runner(seeded):
    """Factory: build an AgentRunner wired to a given FakeLLM + the seeded retriever."""
    from app.agent.runner import AgentRunner

    def _make(fake_llm):
        return AgentRunner(fake_llm, seeded, settings=get_settings())

    return _make


async def create_ticket(body: str, requester: str = "demo.user@corp.com", subject: str | None = None):
    """Helper: create a ticket (intake) and return its id."""
    from app.services.ticket_service import TicketService

    async with session_scope() as session:
        ticket, _ = await TicketService(session).create_ticket(
            body=body, subject=subject, requester_upn=requester
        )
        await session.commit()
        return ticket.id


async def get_ticket(ticket_id: str):
    from app.repositories.ticket_repository import TicketRepository

    async with session_scope() as session:
        return await TicketRepository(session).get_or_404(ticket_id)
