"""
Local Cuisine & Dining Expert — an A2A server agent (port 8105).

Specialises in *what to eat and where*: signature local dishes, the kinds of
places to find them, and a few practical dining tips (tipping, reservations,
dietary notes). Run it on its own with:

    python -m agents.cuisine_expert
"""
from __future__ import annotations

from common.a2a import AgentCard, AgentSkill, build_agent_app, run_agent
from common.llm import chat
from common.persona import persona_aware

PORT = 8105

# The Agent Card is this agent's public "business card". Any A2A client can
# read it at http://127.0.0.1:8105/.well-known/agent-card.json
CARD = AgentCard(
    name="Local Cuisine Expert",
    description="Recommends signature local dishes, where to find them, and dining etiquette.",
    url=f"http://127.0.0.1:{PORT}/",
    skills=[
        AgentSkill(
            id="local_cuisine",
            name="Food & Dining",
            description="Suggest must-try local dishes, the kinds of places to eat, and dining tips.",
            tags=["travel", "food", "dining", "culture"],
            examples=["What should I eat in Kyoto?", "Best street food for a budget trip to Bangkok?"],
        )
    ],
)

SYSTEM = (
    "You are a passionate local-food and dining expert. Given a destination, the "
    "traveler's interests, and travel style (budget / mid-range / luxury), write a "
    "concise guide in Markdown that covers: (1) 4-6 signature local dishes worth "
    "trying (bold the dish name + one-line description), (2) the kinds of places to "
    "find good food at that travel style (e.g. street stalls, markets, neighbourhood "
    "spots, fine dining), and (3) 2-3 practical dining tips (tipping, reservations, "
    "etiquette, dietary notes). Keep it under ~200 words. Do not invent specific "
    "restaurant names, prices, or today's opening hours."
)


async def logic(user_text: str) -> str:
    """The agent's brain: turn the user's request into an answer."""
    return await chat(SYSTEM, user_text, tag="cuisine")


# Wrap the logic into a full A2A HTTP server, with a human voice + negotiation.
app = build_agent_app(CARD, persona_aware("cuisine", logic))

if __name__ == "__main__":
    run_agent(app, PORT)
