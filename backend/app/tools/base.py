"""Tool context and the Tool abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.constants import AgentEventType, ToolMode
from app.db.models import Ticket
from app.schemas.agent import FinalizeResolution
from app.schemas.kb import RetrievalResult
from app.schemas.tool import ToolResult
from app.services.kb_service import KBService
from app.services.verification_service import VerificationService
from app.tools.backends import Backends

EmitFn = Callable[[AgentEventType, dict], Awaitable[None]]

# Resources that may NEVER be granted by the agent (hard deny).
TIER0_RESOURCES = {"domain-admins", "global-admin", "prod-db-root", "kms-keys", "billing-owner"}


@dataclass
class ToolContext:
    """Everything a tool needs, plus mutable signals the loop reads back."""

    session: AsyncSession
    ticket: Ticket
    run_id: str
    attempt: int
    settings: Settings
    kb_service: KBService
    verification_service: VerificationService
    backends: Backends
    emit: EmitFn

    # grounding: ids the agent has actually retrieved this run
    retrieved_ids: set[str] = field(default_factory=set)

    # transient, per-call fields resolved by the executor before policy runs
    target_subject: str | None = None
    identity_verified: bool = False
    target_is_privileged: bool = False

    # outputs the loop inspects after a turn
    awaiting: str | None = None          # 'verification' | 'approval'
    escalation_requested: str | None = None  # reason code
    escalation_meta: dict = field(default_factory=dict)
    finalize: FinalizeResolution | None = None
    requires_privileged_attempted: bool = False
    mutation_performed: bool = False     # a sensitive (non-read) tool actually ran
    send_message_count: int = 0
    retrieval: RetrievalResult | None = None


class Tool(ABC):
    """Base class for all agent tools."""

    name: str = ""
    mode: ToolMode = ToolMode.AUTO
    reversible: bool = True
    description: str = ""

    @abstractmethod
    def input_schema(self) -> dict:
        """Return the JSON schema for this tool's input."""

    def definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema(),
        }

    @abstractmethod
    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        """Run the tool. Must not raise for *expected* failures — return is_error."""

    # Tools that act on a subject override this so the executor can resolve
    # identity verification + privilege before the policy runs.
    def target_subject(self, args: dict, ctx: ToolContext) -> str | None:
        return None
