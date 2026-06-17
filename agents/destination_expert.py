"""
Destination Expert — an A2A server agent (port 8101).

Specialises in *what a place is like*: an overview, the best time to visit,
and local etiquette/tips. Run it on its own with:

    python -m agents.destination_expert
"""
from __future__ import annotations

from common.a2a import AgentCard, AgentSkill, build_agent_app, run_agent
from common.llm import chat

PORT = 8101

# The Agent Card is this agent's public "business card". Any A2A client can
# read it at http://localhost:8101/.well-known/agent-card.json
CARD = AgentCard(
    name="Destination Expert",
    description="Describes a destination: overview, best time to visit, and local tips.",
    url=f"http://127.0.0.1:{PORT}/",
    skills=[
        AgentSkill(
            id="destination_overview",
            name="Destination Overview",
            description="Give an overview of a place, when to go, and etiquette tips.",
            tags=["travel", "destination", "culture"],
            examples=["Tell me about Kyoto", "What's Lisbon like and when should I go?"],
        )
    ],
)

SYSTEM = (
    "You are a seasoned travel destination expert. Given a traveler's request, "
    "write a concise, friendly overview of the destination in Markdown. Cover: a "
    "1-2 sentence vibe, the best time to visit, and 3-4 practical local tips "
    "(etiquette, money, safety). Keep it under ~200 words. Do not invent live data "
    "like today's weather or prices."
)


async def logic(user_text: str) -> str:
    """The agent's brain: turn the user's request into an answer."""
    return await chat(SYSTEM, user_text, tag="destination")


# Wrap the logic into a full A2A HTTP server.
app = build_agent_app(CARD, logic, working_note="Researching the destination...")

if __name__ == "__main__":
    run_agent(app, PORT)
