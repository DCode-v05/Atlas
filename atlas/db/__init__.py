"""Opt-in Postgres persistence (SQLAlchemy async), enabled by ``ATLAS_DATABASE_URL``.

Without the env var, Atlas runs fully in-memory exactly as before. With it, the
org is mirrored into the DB on first boot and runtime/auth state is persisted.
"""

from atlas.db.engine import Base, Database
from atlas.db.seed import clear_history, seed_org

__all__ = ["Base", "Database", "clear_history", "seed_org"]
