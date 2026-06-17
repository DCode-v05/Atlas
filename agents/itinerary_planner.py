"""
Itinerary Planner — an A2A server agent (port 8102).

Specialises in *what to do each day*: a day-by-day plan tailored to the
traveler's interests. Run it on its own with:

    python -m agents.itinerary_planner
"""
from __future__ import annotations

from common.a2a import AgentCard, AgentSkill, build_agent_app, run_agent
from common.llm import chat

PORT = 8102

CARD = AgentCard(
    name="Itinerary Planner",
    description="Builds a day-by-day activity plan for a destination and interests.",
    url=f"http://127.0.0.1:{PORT}/",
    skills=[
        AgentSkill(
            id="day_by_day_itinerary",
            name="Day-by-day Itinerary",
            description="Create a per-day plan given a destination, length, and interests.",
            tags=["travel", "itinerary", "planning"],
            examples=["3 days in Rome for a history lover", "Plan a 5-day foodie trip to Bangkok"],
        )
    ],
)

SYSTEM = (
    "You are an expert trip itinerary planner. Given a destination, a number of "
    "days, and the traveler's interests, produce a realistic day-by-day plan in "
    "Markdown. Use a bold heading per day (e.g. **Day 1**) with a morning, "
    "afternoon, and evening suggestion. Keep activities geographically sensible "
    "and matched to the stated interests. Be concise."
)


async def logic(user_text: str) -> str:
    return await chat(SYSTEM, user_text, tag="itinerary", max_tokens=1100)


app = build_agent_app(CARD, logic, working_note="Drafting a day-by-day plan...")

if __name__ == "__main__":
    run_agent(app, PORT)
