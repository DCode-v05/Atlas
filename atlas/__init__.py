"""Atlas — an A2A (agent-to-agent) communication platform.

A simulated software company of exactly 100 agents that demonstrates *how* agents
communicate like humans: discovery, need-to-know context sharing, redaction,
human-in-the-loop escalation, group vs 1:1 coordination, and intent-carrying
messages — all over a faithful in-process A2A protocol layer.

The package is organised in layers (see CLAUDE.md):
  a2a/          faithful A2A protocol data models (no business logic)
  org/          the company model, the 100-agent generator, org extensions
  bus/          in-process transport: registry, mailbox, discovery, Router
  policy/       the need-to-know decision engine (the graded core)
  conversation/ threads, group sessions, per-agent memory, intent
  hitl/         the single global human-in-the-loop approval queue
  cron/         the simulation engine (15s autonomous burst)
  llm/          the swappable intelligence boundary (Mistral on Amazon Bedrock)
  metrics/      communication-efficiency metrics
  events/       the SSE event schema + broker (the frontend contract)
  api/          the external HTTP edge (REST + SSE)
  store/        in-memory state + JSON snapshot
"""

__version__ = "0.1.0"
