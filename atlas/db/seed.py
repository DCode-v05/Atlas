"""Idempotent first-boot seeding.

Mirrors the seed-generated company into the DB (a durable copy) and provisions an
Ed25519 keypair per agent (its network-auth credential). Idempotent: if the
``agents`` table is already populated, seeding is a no-op, so restarts don't
duplicate or clobber.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select

from atlas.db.models import (
    AgentCredentialRow,
    AgentRow,
    ContextItemRow,
    ConversationRow,
    HitlRow,
    MessageRow,
    PushConfigRow,
    ShareDecisionRow,
    TaskRow,
    TraceSpanRow,
    UserRow,
)
from atlas.network.keys import generate_keypair
from atlas.org.generator import OrgSnapshot


async def clear_history(db) -> dict[str, int]:
    """Delete the runtime conversation record (conversations, messages, share-decisions, tasks,
    HITL requests, trace spans, push configs) — leaving the org and the network membership
    (agents/credentials/users/context-items, sessions/keys) untouched. Returns per-table counts."""
    counts: dict[str, int] = {}
    async with db.session() as s:
        for model in (
            MessageRow, ShareDecisionRow, TraceSpanRow, HitlRow, PushConfigRow, TaskRow, ConversationRow,
        ):
            res = await s.execute(delete(model))
            counts[model.__tablename__] = res.rowcount or 0
        await s.commit()
    return counts


async def seed_org(db, snapshot: OrgSnapshot) -> bool:
    """Seed the org + credentials if empty. Returns True if it seeded, False if already present."""
    async with db.session() as s:
        existing = (await s.execute(select(func.count()).select_from(AgentRow))).scalar_one()
        if existing:
            return False

        for ag in snapshot.agents.values():
            p = ag.profile
            s.add(AgentRow(
                id=ag.id, name=ag.name, email=p.human_email, department=p.department.value,
                role_title=p.role_title, level=int(p.level), clearance=p.clearance, goal=p.goal,
                reports_to=p.reports_to, manages=list(p.manages), teams=list(p.teams),
                projects=list(p.projects), security_cleared=p.security_cleared,
                status=ag.status.value, card=ag.card.model_dump(mode="json"),
            ))
            priv, pub = generate_keypair()
            s.add(AgentCredentialRow(agent_id=ag.id, public_key=pub, private_key=priv, algo="Ed25519"))

        for it in snapshot.items.values():
            s.add(ContextItemRow(
                item_id=it.item_id, owner_agent_id=it.owner_agent_id, title=it.title, body=it.body,
                sensitivity=it.sensitivity.value, scope=it.scope.value, scope_ref=it.scope_ref,
                min_clearance=it.min_clearance, redacted_summary=it.redacted_summary,
                topic_tags=list(it.topic_tags),
            ))

        for u in snapshot.users.values():
            s.add(UserRow(user_id=u.user_id, name=u.name, email=u.email, agent_id=u.agent_id,
                          department=u.department.value, role_title=u.role_title))

        await s.commit()
        return True
