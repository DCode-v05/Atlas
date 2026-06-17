"""
org/employee.py — the ONE generic, onboardable A2A agent.

Every agent in the company — the CEO included — runs this exact code. It boots
as an anonymous "Generalist" and only becomes a "VP Engineering" (or whatever)
by being onboarded. Its logic dispatches on the message's *performative*:

  * propose + an offer  -> role conferral: write the identity, accept.
  * request             -> do the work: either solo, or (if a manager) hire a
                           team and synthesise.

Run one standalone (used by the dynamic runtime in Phase 6):

    python -m org.employee --id E1 --port 9001 --gateway http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse

import config
from org.cognition import do_work
from org.contract_net import bid_score
from org.delegation import run_as_manager, should_manage
from org.envelope import Performative, meta, read
from org.onboarding import Identity, apply_offer
from org.telemetry import Reporter
from protocol.client import A2AClient
from protocol.models import AgentCapabilities, AgentCard, AgentSkill
from protocol.server import build_agent_app, run_agent


class Employee:
    def __init__(self, agent_id: str, port: int, gateway_url: str):
        self.agent_id = agent_id
        self.port = port
        self.gateway_url = gateway_url
        self.identity = Identity(agent_id=agent_id)

    def reset_identity(self) -> None:
        self.identity = Identity(agent_id=self.agent_id)

    def card(self) -> AgentCard:
        """The agent's PUBLIC Agent Card — built from its current identity, so once
        onboarded it advertises the conferred role (this is what discovery returns)."""
        i = self.identity
        url = f"http://{config.HOST}:{self.port}/"
        caps = AgentCapabilities(streaming=True, extensions=[config.ORG_EXT_URI])
        if i.onboarded:
            return AgentCard(
                name=i.role, description=(i.goal or f"{i.role} in the organisation."),
                url=url, version="1.0.0", capabilities=caps,
                skills=[AgentSkill(id="role", name=i.role,
                                   description=i.goal or i.role,
                                   tags=["onboarded", f"depth-{i.depth}"] + (["manager"] if i.manage else []))])
        return AgentCard(
            name=f"{self.agent_id} · Generalist",
            description="A general-knowledge employee, awaiting a role assignment.",
            url=url, capabilities=caps,
            skills=[AgentSkill(id="general", name="General Work",
                               description="Can be onboarded into any role, then do the work or manage a team.",
                               tags=["general", "onboardable"])])

    def build_app(self):
        # pass the bound method so the served card reflects the LIVE identity
        return build_agent_app(self.card, self.logic, working_note="Considering the request…")

    async def logic(self, user_text: str, ctx) -> str:
        env = read(ctx.metadata) or {}
        perf = env.get("performative", Performative.request)
        run_id = env.get("runId", "no-run")
        context_id = ctx.context_id
        reporter = Reporter(run_id, self.agent_id, lambda: self.identity.role, gw=self.gateway_url)

        # --- role conferral (onboarding) ---
        if perf == Performative.propose and isinstance(env.get("offer"), dict):
            apply_offer(self.identity, env["offer"])
            parent = env["offer"].get("hirerId") or "Board"
            await reporter.onboarded(self.identity.role, self.identity.goal,
                                     self.identity.depth, parent)
            await reporter.message(to=parent, to_role=env.get("role", "Board"),
                                   performative=Performative.accept_proposal,
                                   intent=f"accept role {self.identity.role}",
                                   depth=self.identity.depth, context_id=context_id,
                                   text=f"I accept the role of {self.identity.role}.")
            return f"Accepted the role of {self.identity.role}."

        # --- Contract-Net: answer a call-for-proposals with a bid ---
        if perf == Performative.cfp:
            role = env.get("cfpRole", "the role")
            score = bid_score(self.agent_id, role)
            await reporter.message(to=env.get("senderId", "manager"),
                                   to_role=env.get("role", "manager"),
                                   performative=Performative.propose,
                                   intent=f"bid {score} for {role}",
                                   depth=int(env.get("delegationDepth", 0) or 0),
                                   context_id=context_id,
                                   text=f"I can take {role} (confidence {score}).")
            return {"score": score, "agentId": self.agent_id}

        # --- peer consult (mesh): a short reply, no further fan-out ---
        if perf == Performative.query_ref and env.get("consult"):
            mission = env.get("mission") or user_text
            note = (f"{self.identity.role}'s tip: keep '{mission[:40]}' simple and user-first.")
            await reporter.message(to=env.get("senderId", "peer"), to_role=env.get("role", "peer"),
                                   performative=Performative.inform, intent="consult reply",
                                   depth=self.identity.depth, context_id=context_id, text=note)
            return note

        # --- doing the work (a request) ---
        sender_id = env.get("senderId", "Board")
        sender_role = env.get("role", "Board")
        mission = env.get("mission") or user_text
        await reporter.status("working", note=user_text[:80])

        if should_manage(self.identity):
            result = await run_as_manager(self, ctx, user_text, reporter,
                                          run_id=run_id, context_id=context_id, mission=mission)
        else:
            # talk to a peer DIRECTLY before contributing (agent-to-agent, not via
            # the manager): in a group meeting each speaker engages the next peer;
            # in mesh, the first peer. This is the team conversing with itself.
            target = env.get("consultTarget")
            peers = env.get("peers") or []
            if target:
                await self._consult_peer(target, reporter, run_id, context_id, mission)
            elif env.get("topology") == "mesh" and peers:
                await self._consult_peer(peers[0], reporter, run_id, context_id, mission)
            text, tokens = await do_work(self.identity, user_text, mission)
            await reporter.llm(tokens, "do_work")
            result = text

        await reporter.status("done")
        await reporter.message(to=sender_id, to_role=sender_role,
                               performative=Performative.inform, intent="deliver result",
                               depth=self.identity.depth, context_id=context_id, text=result[:200])
        return result

    async def _consult_peer(self, peer: dict, reporter, run_id: str,
                            context_id: str, mission: str) -> None:
        """Ask one peer directly (mesh): query-ref -> their inform."""
        md = meta(Performative.query_ref, role=self.identity.role, intent="consult peer",
                  delegation_depth=self.identity.depth,
                  extra={"runId": run_id, "contextId": context_id, "senderId": self.agent_id,
                         "consult": True, "mission": mission})
        await reporter.message(to=peer["agentId"], to_role=peer.get("role", "peer"),
                               performative=Performative.query_ref,
                               intent=f"consult {peer.get('role', 'peer')}",
                               depth=self.identity.depth, context_id=context_id,
                               text="What should I know from your area?")
        try:
            await A2AClient(peer["url"]).send_text(
                f"Consult for '{mission}'?", context_id=context_id, metadata=md)
        except Exception:
            pass


def _main() -> None:
    ap = argparse.ArgumentParser(description="Run one generic employee A2A server.")
    ap.add_argument("--id", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--gateway", default=config.gateway_url())
    a = ap.parse_args()
    emp = Employee(a.id, a.port, a.gateway)
    run_agent(emp.build_app(), a.port, host=config.HOST)


if __name__ == "__main__":
    _main()
