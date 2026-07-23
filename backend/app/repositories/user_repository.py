"""User persistence + demo seeding."""
from __future__ import annotations

from app.db.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get(self, upn: str) -> User | None:
        return await self.session.get(User, upn)

    async def upsert(self, user: User) -> User:
        existing = await self.session.get(User, user.upn)
        if existing is None:
            self.session.add(user)
            await self.session.flush()
            return user
        for field in ("display_name", "department", "role", "registered_factor", "is_privileged_account"):
            if hasattr(user, field) and getattr(user, field) is not None:
                setattr(existing, field, getattr(user, field))
            elif field == "department" or field == "registered_factor":
                # Allow nullifying optional fields if explicitly set to None, but only if they are actually in __dict__
                if field in user.__dict__:
                    setattr(existing, field, None)
        await self.session.flush()
        return existing

    async def ensure(self, upn: str) -> User:
        """Get a user or create a minimal record (for demo/anonymous intake)."""
        user = await self.get(upn)
        if user is not None:
            return user
        user = User(
            upn=upn,
            display_name=upn.split("@")[0].replace(".", " ").title(),
            registered_factor="sms:•••-•••-4321",
        )
        self.session.add(user)
        await self.session.flush()
        return user
