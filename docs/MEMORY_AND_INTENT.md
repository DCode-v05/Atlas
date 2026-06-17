# Memory, intent & efficient coordination

The base demo was **stateless** — every request started from zero. This layer
makes the orchestrator *stateful*: it remembers conversations, remembers you,
models what you're trying to achieve, and only does the work that's needed.
It adds **no new dependency** (persistence is Python's built‑in `sqlite3`).

Everything here is additive — a first request still produces a full plan exactly
as before. Open the **Conversation Memory** panel in the UI to watch it.

![Conversation memory panel](images/ui-memory.png)

---

## 1. Persistent memory (survives restarts)

[`common/memory.py`](../common/memory.py) is a tiny SQLite store (`data/atlas.db`)
with three kinds of memory:

| Memory | Keyed by | Holds | Example |
|---|---|---|---|
| **Conversation** | `contextId` | current beliefs, intent, and each agent's last result (the cache) | "this chat is about a 7‑day Kyoto trip" |
| **Turn history** | `contextId` | every user request + the plan produced | turn 1, turn 2, … |
| **User memory** | `userId` | durable preferences learned across *all* conversations | "enjoys food", "prefers budget travel" |

Stop and restart the whole stack — your conversation and preferences are still
there (the UI restores them on load).

---

## 2. Context persistence & multi‑turn (the `contextId` finally does something)

A2A messages carry a **`contextId`** — the protocol's hook for threading a
multi‑turn conversation. The base demo generated a fresh one each call and
ignored it. Now:

- The browser keeps one `contextId` per conversation (in `sessionStorage`) and
  sends it with every request; the orchestrator uses it to **recall** prior state.
- That same `contextId` is **threaded into the specialist A2A messages**, so the
  whole conversation shares one id on the wire (you can see it in the log).
- Follow‑ups **update** the prior plan instead of restarting. Try:
  > “Plan a 5‑day food trip to Kyoto” → then → “Actually make it budget and add 2 days”

  The second turn keeps Kyoto + food, changes the days to 7 and the style to
  budget — it remembered.

“**＋ New trip**” calls `POST /api/reset`, which forgets the conversation but
*keeps* your long‑term preferences.

---

## 3. Intent & motivations (a light BDI + FIPA flavor)

Classic agent theory talks about **beliefs, desires, intentions** (BDI) and about
the **performative** of a message — its communicative intent — from agent
languages like **FIPA‑ACL**. This prototype models both, simply:

- One `understand()` call updates the orchestrator's **beliefs**
  `{destination, days, interests, travelStyle}` and the conversation's **intent**
  `{goal, constraints, openQuestions}` — the *motivation* behind the chat. Both
  are shown in the memory panel and persisted.
- Every delegation message carries **`metadata.performative = "request"`** plus an
  **`intent`** string explaining *why* the orchestrator is asking this agent
  (e.g. *“Ground packing advice in a live forecast”*). You'll see it in the log.
- Each specialist declares an explicit **role** and **motivation** (in
  [`common/config.py`](../common/config.py)), shown on its Discovered‑Agent card.

> This is a teaching‑sized model, not a full BDI reasoner — but it makes "roles,
> intentions, and the motivation behind a conversation" concrete and visible.

---

## 4. Coordination efficiency (do less work)

Instead of always calling all four specialists, the orchestrator is selective:

- **Selection** — when `understand()` reports which beliefs **changed**, a simple
  rule map ([`SELECTION_RULES`](../orchestrator/orchestrator.py)) picks only the
  affected agents. Change the *budget style* → only Budget + Itinerary re‑run.
  Change nothing → **zero** A2A calls (just re‑synthesise).
- **Caching** — unchanged agents' answers are reused from the conversation's
  stored `results` (persisted, so it even survives a restart). The UI marks those
  nodes **“reused (cached)”** in violet.
- **Retries** — specialist A2A calls and Groq calls retry with backoff on
  transient errors before giving up (and an offline agent is still skipped
  gracefully).

| Belief changed | Specialists re‑run |
|---|---|
| destination | all four |
| days | itinerary, budget, weather |
| interests | destination, itinerary |
| travelStyle | itinerary, budget |
| (nothing material) | none — all reused |

---

## The new request lifecycle

```
recall ──► understand ──► discover ──► SELECT ──► delegate(selected) ──► synthesise ──► persist
 (memory)   (beliefs+      (cards +     (changed   (parallel, cached     (honour       (save state +
            intent)         roles)       → agents)   reused, retried)      intent)       turn + prefs)
```

It's still the **same `plan_trip`** the orchestrator A2A agent (`:8100`) exposes —
so multi‑turn works over A2A too: reuse the same `contextId` across calls.

---

## What's honest about the scope
- The "user" is a single local demo user (`userId="local"`); a real app would key
  memory per authenticated account.
- `understand()` is one pragmatic LLM call (with an offline mock), not a formal
  belief‑revision system.
- Preference extraction is best‑effort; it stores short facts, not a user model.

Back to: [A2A_EXPLAINED.md](A2A_EXPLAINED.md) ·
[MCP_AND_COMPOSITION.md](MCP_AND_COMPOSITION.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
