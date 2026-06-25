"""``NetworkService`` — the authenticated-network control plane.

An agent **joins** the network by proving possession of its Ed25519 key
(challenge → signature → verify), after which the network issues a short-lived,
**scoped JWT** backed by a revocable DB **session**. The agent then communicates
freely (the JWT is presented and verified — signature + expiry + session-not-
revoked) without re-authenticating, while the Policy Engine still authorises every
message.

Honesty note: in this single-process demo the network can also *one-click* join an
agent using its server-held private key — a convenience. The genuinely-better-than-
an-API-key properties are real regardless: asymmetric proof (no static shared
secret), scoped claims, expiry, and **per-identity revocable sessions**. The real
model (each agent holds its own key, signing client-side) is the engine.md future.
"""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timezone
from typing import Optional

import jwt
from sqlalchemy import delete, select, update

from atlas.a2a.ids import new_id, utcnow
from atlas.db.models import AgentCredentialRow, AuthChallengeRow, NetworkKeyRow, NetworkSessionRow
from atlas.events import EventBroker, EventType, NetworkMemberPayload
from atlas.network.keys import generate_keypair, sign, verify
from atlas.org.generator import OrgSnapshot

CHALLENGE_TTL = 60  # seconds
ISSUER = "atlas-network"


def _now() -> int:
    return int(utcnow().timestamp())


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class NetworkService:
    def __init__(self, db, broker: EventBroker, snapshot: OrgSnapshot, *, session_ttl: int = 43200) -> None:
        self.db = db
        self.broker = broker
        self.snapshot = snapshot
        self.session_ttl = session_ttl
        self._priv_pem: Optional[str] = None
        self._pub_pem: Optional[str] = None
        self._members: dict[str, dict] = {}  # agent_id -> {session_id, scope, expires_at}
        self.active = False  # set True by init(); gating stays OFF until the network is live

    # ── lifecycle ───────────────────────────────────────────────────────────
    async def init(self) -> None:
        """Load (or create) the network signing keypair and re-hydrate live sessions."""
        async with self.db.session() as s:
            row = (await s.execute(select(NetworkKeyRow).where(NetworkKeyRow.id == "signing"))).scalar_one_or_none()
            if row is None:
                priv, pub = generate_keypair()
                s.add(NetworkKeyRow(id="signing", private_key=priv, public_key=pub))
                await s.commit()
                self._priv_pem, self._pub_pem = priv, pub
            else:
                self._priv_pem, self._pub_pem = row.private_key, row.public_key

        now = _now()
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(NetworkSessionRow).where(
                        NetworkSessionRow.revoked == False,  # noqa: E712
                        NetworkSessionRow.expires_at > now,
                    )
                )
            ).scalars().all()
        for r in rows:  # sessions survive a restart — no re-auth needed
            self._members[r.agent_id] = {"session_id": r.session_id, "scope": r.scope, "expires_at": _iso(r.expires_at)}
        self.active = True

    # ── membership ──────────────────────────────────────────────────────────
    def is_member(self, agent_id: str) -> bool:
        return agent_id in self._members

    def member_ids(self) -> set[str]:
        return set(self._members)

    def members(self) -> list[dict]:
        return [{"agent_id": a, **info} for a, info in self._members.items()]

    # ── challenge / response ────────────────────────────────────────────────
    async def create_challenge(self, agent_id: str) -> Optional[dict]:
        if agent_id not in self.snapshot.agents:
            return None
        nonce = secrets.token_urlsafe(32)
        expires = _now() + CHALLENGE_TTL
        async with self.db.session() as s:
            s.add(AuthChallengeRow(nonce=nonce, agent_id=agent_id, expires_at=expires))
            await s.commit()
        return {"agent_id": agent_id, "nonce": nonce, "expires_at": _iso(expires)}

    async def authenticate(self, agent_id: str, nonce: str, signature: bytes) -> Optional[dict]:
        """Verify a signed challenge and, on success, issue a session + JWT (the agent joins)."""
        async with self.db.session() as s:
            ch = (await s.execute(select(AuthChallengeRow).where(AuthChallengeRow.nonce == nonce))).scalar_one_or_none()
            valid = ch is not None and ch.agent_id == agent_id and ch.expires_at > _now()
            if ch is not None:  # single-use: consume the nonce on any attempt
                await s.execute(delete(AuthChallengeRow).where(AuthChallengeRow.nonce == nonce))
                await s.commit()
            if not valid:
                return None
            cred = (
                await s.execute(select(AgentCredentialRow).where(AgentCredentialRow.agent_id == agent_id))
            ).scalar_one_or_none()
        if cred is None or not verify(cred.public_key, nonce.encode(), signature):
            return None
        return await self._issue(agent_id)

    async def authenticate_oneclick(self, agent_id: str) -> Optional[dict]:
        """Operator convenience: run the real challenge/response server-side with the agent's stored key."""
        ch = await self.create_challenge(agent_id)
        if ch is None:
            return None
        async with self.db.session() as s:
            cred = (
                await s.execute(select(AgentCredentialRow).where(AgentCredentialRow.agent_id == agent_id))
            ).scalar_one_or_none()
        if cred is None:
            return None
        return await self.authenticate(agent_id, ch["nonce"], sign(cred.private_key, ch["nonce"].encode()))

    async def _issue(self, agent_id: str) -> dict:
        ag = self.snapshot.agents[agent_id]
        p = ag.profile
        session_id = new_id("ses-")
        now, exp = _now(), _now() + self.session_ttl
        scope = {
            "department": p.department.value, "role": p.role_title, "level": int(p.level),
            "clearance": p.clearance, "teams": list(p.teams), "projects": list(p.projects),
            "scopes": ["network:communicate"],
        }
        async with self.db.session() as s:
            # one active session per agent — supersede any prior one
            await s.execute(
                update(NetworkSessionRow)
                .where(NetworkSessionRow.agent_id == agent_id, NetworkSessionRow.revoked == False)  # noqa: E712
                .values(revoked=True, revoked_at=now)
            )
            s.add(NetworkSessionRow(session_id=session_id, agent_id=agent_id, scope=scope,
                                    issued_at=now, expires_at=exp, revoked=False))
            await s.commit()

        token = jwt.encode(
            {"iss": ISSUER, "sub": agent_id, "iat": now, "exp": exp, "jti": session_id, **scope},
            self._priv_pem, algorithm="EdDSA",
        )
        self._members[agent_id] = {"session_id": session_id, "scope": scope, "expires_at": _iso(exp)}
        self._emit(EventType.NETWORK_JOINED, ag, session_id)
        return {"token": token, "token_type": "Bearer", "agent_id": agent_id,
                "session_id": session_id, "expires_at": _iso(exp), "scope": scope}

    # ── verification ────────────────────────────────────────────────────────
    def verify_token(self, token: str) -> Optional[dict]:
        """Return the JWT claims iff the signature, issuer, expiry AND live session all check out."""
        try:
            claims = jwt.decode(token, self._pub_pem, algorithms=["EdDSA"], issuer=ISSUER,
                                options={"require": ["exp", "sub", "jti"]})
        except Exception:
            return None
        info = self._members.get(claims.get("sub"))
        if info is None or info["session_id"] != claims.get("jti"):
            return None  # session revoked or superseded
        return claims

    # ── disconnect ──────────────────────────────────────────────────────────
    async def disconnect(self, agent_id: str) -> bool:
        info = self._members.pop(agent_id, None)
        async with self.db.session() as s:
            await s.execute(
                update(NetworkSessionRow)
                .where(NetworkSessionRow.agent_id == agent_id, NetworkSessionRow.revoked == False)  # noqa: E712
                .values(revoked=True, revoked_at=_now())
            )
            await s.commit()
        if info is None:
            return False
        ag = self.snapshot.agents.get(agent_id)
        if ag is not None:
            self._emit(EventType.NETWORK_LEFT, ag, info["session_id"])
        return True

    def _emit(self, etype: EventType, ag, session_id: str) -> None:
        self.broker.emit(etype, NetworkMemberPayload(
            agent_id=ag.id, name=ag.name, department=ag.profile.department.value,
            role=ag.profile.role_title, session_id=session_id, members=len(self._members),
        ))


def b64decode(s: str) -> bytes:
    return base64.b64decode(s)
