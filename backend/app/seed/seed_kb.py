"""Load seed KB articles + demo users."""
from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.kb import KBArticleIn

logger = get_logger(__name__)

_SEED_PATH = Path(__file__).with_name("kb_articles.yaml")


def load_seed_articles() -> list[KBArticleIn]:
    raw = yaml.safe_load(_SEED_PATH.read_text(encoding="utf-8")) or []
    return [KBArticleIn.model_validate(item) for item in raw]


DEMO_USERS = [
    {"upn": "demo.user@corp.com", "display_name": "Demo User", "department": "Sales",
     "registered_factor": "sms:•••-•••-4321"},
    {"upn": "jordan.lee@corp.com", "display_name": "Jordan Lee", "department": "Marketing",
     "registered_factor": "sms:•••-•••-8876"},
    {"upn": "admin@corp.com", "display_name": "Domain Admin", "department": "IT",
     "registered_factor": "app:authenticator", "is_privileged_account": True},
]


async def seed_demo_users(session: AsyncSession) -> int:
    repo = UserRepository(session)
    for spec in DEMO_USERS:
        await repo.upsert(User(**spec))
    await session.flush()
    return len(DEMO_USERS)
