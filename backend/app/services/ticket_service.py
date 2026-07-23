"""Ticket intake orchestration (the synchronous part of a request).

Keeps the HTTP path fast: redact -> dedup -> persist -> return. The expensive
Perceive/Plan/Act/Reflect loop is run asynchronously by the AgentRunner; this
service intentionally has no dependency on the agent (avoids cycles).
"""
from __future__ import annotations

import hashlib
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TicketStatus
from app.core.logging import get_logger
from app.db.models import Ticket
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.services.redaction_service import RedactionService

logger = get_logger(__name__)

DEFAULT_REQUESTER = "demo.user@corp.com"
_WORD_RE = re.compile(r"[a-z0-9]+")


def _dedupe_key(text: str) -> str:
    tokens = sorted(set(_WORD_RE.findall(text.lower())))
    digest = hashlib.md5(" ".join(tokens).encode()).hexdigest()  # noqa: S324 - non-crypto use
    return digest[:32]


class TicketService:
    def __init__(self, session: AsyncSession, redaction: RedactionService | None = None) -> None:
        self.session = session
        self.tickets = TicketRepository(session)
        self.users = UserRepository(session)
        self.redaction = redaction or RedactionService()

    async def create_ticket(
        self,
        *,
        body: str,
        subject: str | None = None,
        requester_upn: str | None = None,
        channel: str = "chat",
    ) -> tuple[Ticket, str | None]:
        requester = requester_upn or DEFAULT_REQUESTER
        await self.users.ensure(requester)

        report = self.redaction.process(body)
        clean_body = report.text
        clean_subject = self.redaction.redact(subject) if subject else clean_body[:120]

        dedupe_key = _dedupe_key(clean_body)
        duplicate = await self.tickets.find_recent_duplicate(
            requester_upn=requester, dedupe_key=dedupe_key
        )

        ticket = Ticket(
            requester_upn=requester,
            channel=channel,
            subject=clean_subject,
            status=TicketStatus.NEW.value,
            dedupe_key=dedupe_key,
            injection_flag=report.injection_suspected,
            duplicate_of=duplicate.id if duplicate else None,
        )
        await self.tickets.create(ticket)
        await self.tickets.add_message(
            ticket_id=ticket.id, role="user", body=clean_body, author=requester
        )
        logger.info(
            "ticket_created",
            ticket_id=ticket.id,
            requester=requester,
            duplicate_of=ticket.duplicate_of,
            injection=report.injection_suspected,
        )
        return ticket, (duplicate.id if duplicate else None)

    async def add_user_message(self, *, ticket: Ticket, body: str, author: str | None = None) -> str:
        report = self.redaction.process(body)
        await self.tickets.add_message(
            ticket_id=ticket.id, role="user", body=report.text, author=author or ticket.requester_upn
        )
        if report.injection_suspected:
            ticket.injection_flag = True
        await self.session.flush()
        return report.text
