"""Pluggable action backends (mock implementations for Phase 0)."""
from __future__ import annotations

from dataclasses import dataclass

from app.tools.backends.endpoint import EndpointBackend, MockEndpointBackend
from app.tools.backends.identity import IdentityBackend, MockIdentityBackend


@dataclass
class Backends:
    """Container injected into the tool context (Dependency Inversion seam)."""

    identity: IdentityBackend
    endpoint: EndpointBackend


def default_backends() -> Backends:
    return Backends(identity=MockIdentityBackend(), endpoint=MockEndpointBackend())


__all__ = [
    "Backends",
    "default_backends",
    "IdentityBackend",
    "MockIdentityBackend",
    "EndpointBackend",
    "MockEndpointBackend",
]
