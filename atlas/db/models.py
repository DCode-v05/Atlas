"""SQLAlchemy ORM models — portable across Postgres (prod) and SQLite (tests).

Every list/dict column uses the portable ``JSON`` type (no Postgres-only
``ARRAY``/``JSONB``), so the identical schema runs on both engines. The org tables
mirror the seed-generated company (a durable copy); ``agent_credentials`` holds
each agent's network-auth keypair. Runtime + session tables are added in later
phases.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from atlas.a2a.ids import utcnow
from atlas.db.engine import Base


class AgentRow(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    department = Column(String, nullable=False)
    role_title = Column(String, nullable=False)
    level = Column(Integer, nullable=False)
    clearance = Column(Integer, nullable=False)
    goal = Column(Text, default="")
    reports_to = Column(String, nullable=True)
    manages = Column(JSON, default=list)
    teams = Column(JSON, default=list)
    projects = Column(JSON, default=list)
    security_cleared = Column(Boolean, default=False)
    status = Column(String, default="idle")
    card = Column(JSON, nullable=False)


class ContextItemRow(Base):
    __tablename__ = "context_items"

    # Item ids are TEMPLATE-derived (e.g. "item-roadmap-public"), so they are identical across
    # orgs in a federation — the only seed table whose key is NOT seed-disjoint. The seeder
    # namespaces the VALUE by org for non-primary orgs (e.g. "globex:item-roadmap-public") so
    # every org's items coexist in one DB. The key is namespaced in the value (not as a separate
    # column) deliberately: it keeps this table's schema byte-identical, so an EXISTING persisted
    # database keeps working without a migration (there is no Alembic — see seed.py).
    item_id = Column(String, primary_key=True)
    owner_agent_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    sensitivity = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    scope_ref = Column(String, nullable=True)
    min_clearance = Column(Integer, default=1)
    redacted_summary = Column(Text, nullable=True)
    topic_tags = Column(JSON, default=list)


class UserRow(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    agent_id = Column(String, nullable=False)
    department = Column(String, nullable=False)
    role_title = Column(String, nullable=False)


class AgentCredentialRow(Base):
    __tablename__ = "agent_credentials"

    agent_id = Column(String, primary_key=True)
    public_key = Column(Text, nullable=False)
    # DEMO: the private key is held server-side so the operator can one-click "join" an agent.
    # In the real (engine-fleet) model each agent holds its own key; the network stores only the public key.
    private_key = Column(Text, nullable=False)
    algo = Column(String, default="Ed25519")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class NetworkKeyRow(Base):
    """Singleton — the network's own Ed25519 keypair used to sign/verify session JWTs."""

    __tablename__ = "network_keys"

    id = Column(String, primary_key=True)  # "signing"
    private_key = Column(Text, nullable=False)
    public_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AuthChallengeRow(Base):
    """A single-use, short-TTL, agent-bound nonce for challenge/response authentication."""

    __tablename__ = "auth_challenges"

    nonce = Column(String, primary_key=True)
    agent_id = Column(String, nullable=False)
    expires_at = Column(Integer, nullable=False)  # epoch seconds (portable across sqlite/postgres)


class NetworkSessionRow(Base):
    """A revocable session — the durable backing for an issued JWT (jti == session_id)."""

    __tablename__ = "network_sessions"

    session_id = Column(String, primary_key=True)
    agent_id = Column(String, nullable=False, index=True)
    scope = Column(JSON, nullable=False)
    issued_at = Column(Integer, nullable=False)  # epoch seconds
    expires_at = Column(Integer, nullable=False)
    revoked = Column(Boolean, default=False)
    revoked_at = Column(Integer, nullable=True)


# ─── Runtime / conversation record (write-through persistence) ─────────────────


class ConversationRow(Base):
    """A conversation header — the prompt/goal that opened a context. Persisted so the
    timeline + history can be rebuilt after a refresh/restart (messages/decisions/tasks
    join to it by ``context_id``)."""

    __tablename__ = "conversations"

    context_id = Column(String, primary_key=True)
    prompt = Column(Text, default="")
    kind = Column(String, default="user")  # user | cron
    routed_to = Column(String, nullable=True)
    routed_to_name = Column(String, default="")
    task_id = Column(String, nullable=True)
    created_at = Column(Integer, nullable=True)


class TaskRow(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    context_id = Column(String, nullable=False, index=True)
    state = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(Integer, nullable=True)
    updated_at = Column(Integer, nullable=True)


class MessageRow(Base):
    __tablename__ = "messages"

    # seq is a monotonic surrogate so intra-conversation order is exact — message_id is a
    # string and ts is second-granularity, so several messages in the same second would tie.
    seq = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String, nullable=False, unique=True, index=True)  # the A2A message id
    context_id = Column(String, nullable=True, index=True)
    task_id = Column(String, nullable=True)
    sender = Column(String, nullable=False)
    recipients = Column(JSON, default=list)
    mode = Column(String, default="individual")
    role = Column(String, default="agent")
    text = Column(Text, default="")
    thinking = Column(Text, nullable=True)
    intent = Column(JSON, nullable=True)
    thread_id = Column(String, nullable=True)
    group_id = Column(String, nullable=True)
    ts = Column(Integer, nullable=True)


class ShareDecisionRow(Base):
    __tablename__ = "share_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    context_id = Column(String, nullable=True, index=True)
    kind = Column(String, nullable=False)  # shared | redacted | denied | reused
    item_id = Column(String)
    title = Column(String)
    sender = Column(String)
    recipient = Column(String)
    sensitivity = Column(String)
    rule_id = Column(String)
    reason = Column(Text)
    summary = Column(Text, nullable=True)
    ts = Column(Integer, nullable=True)


class HitlRow(Base):
    __tablename__ = "hitl_requests"

    request_id = Column(String, primary_key=True)
    task_id = Column(String)
    context_id = Column(String, nullable=True, index=True)
    owner_agent_id = Column(String)
    requester_agent_id = Column(String)
    item_id = Column(String)
    item_title = Column(String)
    sensitivity = Column(String)
    proposed_outcome = Column(String)
    reason = Column(Text)
    state = Column(String, default="pending")
    decided_by = Column(String, nullable=True)
    decided_outcome = Column(String, nullable=True)
    created_at = Column(Integer, nullable=True)
    decided_at = Column(Integer, nullable=True)


class PushConfigRow(Base):
    __tablename__ = "push_configs"

    id = Column(String, primary_key=True)
    task_id = Column(String, nullable=True, index=True)
    url = Column(String, nullable=False)
    token = Column(String, nullable=True)
    authentication = Column(JSON, nullable=True)


class TraceSpanRow(Base):
    __tablename__ = "trace_spans"

    span_id = Column(String, primary_key=True)
    context_id = Column(String, nullable=True, index=True)
    agent_id = Column(String)
    kind = Column(String)
    summary = Column(Text)
    live = Column(Boolean, default=False)
    detail = Column(Text, nullable=True)
    ts = Column(String, nullable=True)
