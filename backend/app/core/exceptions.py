"""Domain exception hierarchy.

These map cleanly onto HTTP status codes in the API layer (see api/errors.py),
keeping HTTP concerns out of services and the agent.
"""
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for all expected, handled domain errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ValidationFailure(DomainError):
    """Domain-level validation error (distinct from pydantic's ValidationError)."""

    status_code = 422
    code = "validation_failed"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class AuthorizationError(DomainError):
    status_code = 403
    code = "forbidden"


class PolicyDeniedError(DomainError):
    """Raised when the tool policy engine refuses an action."""

    status_code = 403
    code = "policy_denied"


class VerificationError(DomainError):
    status_code = 400
    code = "verification_failed"


class ToolExecutionError(DomainError):
    """A tool backend failed. Surfaced to the model as a recoverable tool error."""

    status_code = 502
    code = "tool_execution_failed"


class LLMError(DomainError):
    """The language model call failed after retries."""

    status_code = 503
    code = "llm_unavailable"


class ConfigurationError(DomainError):
    status_code = 500
    code = "configuration_error"
