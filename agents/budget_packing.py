"""
Budget & Packing Advisor — an A2A server agent (port 8103).

Specialises in *money and what to bring*: a rough budget estimate and a
packing list tuned to the trip style. Run it on its own with:

    python -m agents.budget_packing
"""
from __future__ import annotations

from common.a2a import AgentCard, AgentSkill, build_agent_app, run_agent
from common.llm import chat
from common.persona import persona_aware

PORT = 8103

CARD = AgentCard(
    name="Budget & Packing Advisor",
    description="Estimates a rough trip budget and suggests a packing list.",
    url=f"http://127.0.0.1:{PORT}/",
    skills=[
        AgentSkill(
            id="budget_and_packing",
            name="Budget & Packing",
            description="Estimate daily/total costs and produce a packing checklist.",
            tags=["travel", "budget", "packing"],
            examples=["Budget for 4 budget days in Hanoi", "What should I pack for luxury Dubai?"],
        )
    ],
)

SYSTEM = (
    "You are a practical travel budget and packing advisor. Given a destination, "
    "number of days, and travel style (budget / mid-range / luxury), produce in "
    "Markdown: (1) a short budget estimate with a rough per-day and total figure "
    "in USD, noting it is an approximation, and (2) a concise bulleted packing "
    "list suited to the destination and style. Be concise and clearly a rough guide."
)


async def logic(user_text: str) -> str:
    return await chat(SYSTEM, user_text, tag="budget")


app = build_agent_app(CARD, persona_aware("budget", logic))

if __name__ == "__main__":
    run_agent(app, PORT)
