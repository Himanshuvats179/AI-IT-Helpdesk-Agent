"""HTTP API surface tests (ASGI, lifespan-managed, scripted LLM injected)."""
from __future__ import annotations

import asyncio

import httpx
import pytest_asyncio

from app.config import get_settings
from app.db.base import dispose_engine
from app.main import create_app
from tests.conftest import make_retriever
from tests.fakes.fake_llm import FakeLLM, finalize_call


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}")
    get_settings.cache_clear()
    await dispose_engine()

    fake = FakeLLM(
        perception={"primary_category": "vpn", "urgency": "medium", "impact": "individual",
                    "summary": "vpn won't connect", "confidence": 0.92},
        script=[
            [("search_kb", {"query": "vpn won't connect", "category": "vpn"})],
            [finalize_call(cited=["KB-0003"], answer="Re-import the VPN profile and reconnect.")],
        ],
    )
    app = create_app(provider=fake, retriever=make_retriever(), start_scheduler=False, seed=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    await dispose_engine()
    get_settings.cache_clear()


async def _poll_status(client, ticket_id, terminal=("resolved", "escalated", "follow_up_pending"), tries=100):
    for _ in range(tries):
        resp = await client.get(f"/v1/tickets/{ticket_id}")
        status = resp.json()["status"]
        if status in terminal:
            return status
        await asyncio.sleep(0.05)
    return status


async def test_healthz(api):
    resp = await api.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readyz_reports_indexed_kb(api):
    resp = await api.get("/readyz")
    body = resp.json()
    assert body["db"] is True
    assert body["kb_articles_indexed"] > 0


async def test_kb_search_endpoint(api):
    resp = await api.get("/v1/admin/kb/search", params={"q": "vpn won't connect", "category": "vpn"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["no_good_match"] is False
    assert any(h["article_id"] == "KB-0003" for h in body["hits"])


async def test_list_tickets_empty(api):
    resp = await api.get("/v1/tickets")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_create_ticket_runs_to_resolution(api):
    resp = await api.post("/v1/tickets", json={"body": "My VPN won't connect to the network."})
    assert resp.status_code == 202
    ticket_id = resp.json()["ticket_id"]

    status = await _poll_status(api, ticket_id)
    assert status == "resolved"

    detail = (await api.get(f"/v1/tickets/{ticket_id}")).json()
    assert any(m["role"] == "agent" for m in detail["messages"])

    runs = (await api.get(f"/v1/tickets/{ticket_id}/runs")).json()
    assert runs and runs[0]["outcome"] == "resolved"
    assert any(tc["tool_name"] == "finalize_resolution" for tc in runs[0]["tool_calls"])


async def test_unknown_ticket_404(api):
    resp = await api.get("/v1/tickets/tkt_does_not_exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
