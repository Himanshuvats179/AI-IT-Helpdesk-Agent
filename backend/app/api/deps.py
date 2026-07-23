"""FastAPI dependency providers (composition root accessors)."""
from __future__ import annotations

from fastapi import Request

from app.agent.runner import AgentRunner
from app.db.session import get_session  # re-exported for routers
from app.services.notification_service import EventBus
from app.services.retrieval.retriever import HybridRetriever

__all__ = ["get_session", "get_runner", "get_retriever", "get_bus"]


def get_runner(request: Request) -> AgentRunner:
    return request.app.state.runner


def get_retriever(request: Request) -> HybridRetriever:
    return request.app.state.retriever


def get_bus(request: Request) -> EventBus:
    return request.app.state.event_bus
