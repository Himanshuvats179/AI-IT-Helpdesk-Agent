"""Repository layer: the only place that talks SQLAlchemy to the DB.

Repositories accept an :class:`AsyncSession` and never commit — transaction
boundaries are owned by the caller (request dependency or worker session scope).
This keeps services persistence-agnostic and easy to unit test.
"""
