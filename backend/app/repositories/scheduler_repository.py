"""Scheduled-job persistence — the single durable timer mechanism.

SQLite lacks ``FOR UPDATE SKIP LOCKED``, so exactly-once claiming is emulated
with an atomic conditional UPDATE: a worker only wins a job if it flips the row
from ``pending`` to ``running`` in one statement (rowcount == 1). The unique
``idempotency_key`` prevents duplicate scheduling of the same logical timer.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.ids import utcnow
from app.db.models import ScheduledJob
from app.repositories.base import BaseRepository


class SchedulerRepository(BaseRepository):
    async def create_job(
        self,
        *,
        kind: str,
        ticket_id: str,
        run_at: datetime,
        idempotency_key: str,
        payload: dict | None = None,
    ) -> ScheduledJob | None:
        """Create a job; returns None if an identical idempotency_key already exists."""
        job = ScheduledJob(
            kind=kind,
            ticket_id=ticket_id,
            run_at=run_at,
            idempotency_key=idempotency_key,
            payload=payload or {},
        )
        # Use a SAVEPOINT so a duplicate-key collision rolls back ONLY this insert,
        # never the caller's surrounding work (e.g. a just-committed resolution).
        try:
            async with self.session.begin_nested():
                self.session.add(job)
                await self.session.flush()
        except IntegrityError:
            return None
        return job

    async def claim_due(self, *, owner: str, limit: int = 10, lease_seconds: int = 120) -> list[ScheduledJob]:
        """Atomically claim up to ``limit`` due jobs for this worker."""
        now = utcnow()
        lease_until = now + timedelta(seconds=lease_seconds)

        stmt = (
            select(ScheduledJob.id)
            .where(ScheduledJob.status == "pending", ScheduledJob.run_at <= now)
            .order_by(ScheduledJob.run_at)
            .limit(limit)
        )
        candidate_ids = list((await self.session.scalars(stmt)).all())

        claimed: list[ScheduledJob] = []
        for job_id in candidate_ids:
            result = await self.session.execute(
                update(ScheduledJob)
                .where(ScheduledJob.id == job_id, ScheduledJob.status == "pending")
                .values(
                    status="running",
                    lease_owner=owner,
                    lease_expires_at=lease_until,
                    attempts=ScheduledJob.attempts + 1,
                    updated_at=now,
                )
            )
            if result.rowcount == 1:
                job = await self.session.get(ScheduledJob, job_id)
                if job is not None:
                    claimed.append(job)
        await self.session.flush()
        return claimed

    async def complete(self, job: ScheduledJob, *, status: str = "done", error: str | None = None) -> None:
        job.status = status
        job.last_error = error
        job.lease_owner = None
        job.lease_expires_at = None
        await self.session.flush()

    async def reclaim_expired_leases(self) -> int:
        """Return stuck 'running' jobs whose lease expired back to 'pending'."""
        now = utcnow()
        result = await self.session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.status == "running", ScheduledJob.lease_expires_at < now)
            .values(status="pending", lease_owner=None, lease_expires_at=None, updated_at=now)
        )
        await self.session.flush()
        return int(result.rowcount or 0)

    async def cancel_for_ticket(self, ticket_id: str, kind: str | None = None) -> int:
        stmt = (
            update(ScheduledJob)
            .where(ScheduledJob.ticket_id == ticket_id, ScheduledJob.status == "pending")
            .values(status="cancelled", updated_at=utcnow())
        )
        if kind:
            stmt = stmt.where(ScheduledJob.kind == kind)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)
