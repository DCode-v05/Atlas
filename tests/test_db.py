"""DB-foundation smoke tests (SQLite / aiosqlite — no Postgres needed).

The schema + idempotent org seeding are engine-agnostic (portable JSON columns),
so SQLite here exercises the same code the Postgres deployment runs.
"""

from __future__ import annotations

from sqlalchemy import func, select

from atlas.config import Settings
from atlas.db import Database, seed_org
from atlas.db.models import AgentCredentialRow, AgentRow, ContextItemRow, UserRow
from atlas.org.generator import generate_org
from atlas.runtime import build_runtime


async def test_seed_mirrors_org_and_provisions_credentials(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/atlas.db")
    await db.create_all()
    snap = generate_org(42)

    assert await seed_org(db, snap) is True
    async with db.session() as s:
        agents = (await s.execute(select(func.count()).select_from(AgentRow))).scalar_one()
        creds = (await s.execute(select(func.count()).select_from(AgentCredentialRow))).scalar_one()
        items = (await s.execute(select(func.count()).select_from(ContextItemRow))).scalar_one()
        users = (await s.execute(select(func.count()).select_from(UserRow))).scalar_one()
    assert agents == 100 and creds == 100 and items == 18 and users == 100

    # idempotent: re-seeding a populated DB is a no-op
    assert await seed_org(db, snap) is False
    async with db.session() as s:
        again = (await s.execute(select(func.count()).select_from(AgentRow))).scalar_one()
        ids = [r[0] for r in (await s.execute(select(AgentRow.id))).all()]
    assert again == 100
    # agent ids are the opaque SEP-<16 digits> form
    assert all(i.startswith("SEP-") and len(i) == 20 and i[4:].isdigit() for i in ids)

    await db.dispose()


def test_runtime_db_is_opt_in(offline_llm):
    rt = build_runtime(Settings(seed=42, _env_file=None), step_delay=0.0, llm=offline_llm)
    assert rt.db is None  # no DATABASE_URL -> fully in-memory
    rt2 = build_runtime(
        Settings(seed=42, database_url="sqlite+aiosqlite:///:memory:", _env_file=None),
        step_delay=0.0,
        llm=offline_llm,
    )
    assert rt2.db is not None  # an inert (not-yet-connected) handle exists
