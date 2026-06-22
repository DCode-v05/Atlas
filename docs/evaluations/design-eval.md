# Evaluation: How realistically Atlas's agent-to-agent conversations mirror human communication in software organisations

**Scope.** Atlas is a demonstrator of *how agents communicate, like humans* inside a
simulated 100-agent software company. This document evaluates **communication
realism** — does the way Atlas agents route, ask, share, escalate, and coordinate
resemble how people actually talk inside software/product orgs? It is **not** an
assessment of task throughput or model quality. Every claim about human behaviour is
cited to a public source; every claim about Atlas is cited to a specific file and,
where useful, a line range.

---

## 1. Intro & method

I researched human communication patterns in software/product companies across the
dimensions the prompt named — synchronous vs asynchronous communication, standups and
status cadence, incident response (on-call, war rooms, blameless postmortems),
need-to-know / least-privilege confidentiality, escalation paths and decision rights
(RACI), 1:1 vs group coordination, cross-functional communication, intent/context in
messages, Slack/meeting culture and information overload, and psychological safety. I
ran multiple web searches and drew on reputable engineering/management sources. I then
read the Atlas implementation directly: the orchestrator pipeline, the cron simulator,
the router chokepoint, the org generator, the extension models, the LLM boundary, and
the metrics collector. Ratings below are grounded in what the **code actually executes**.

### Sources (human behaviour)

1. GitLab Handbook — *How to embrace asynchronous communication for remote work*: <https://handbook.gitlab.com/handbook/company/culture/all-remote/asynchronous/>
2. GitLab Handbook — *Engineering Communication* (clear, concise, transparent, async, frequent): <https://handbook.gitlab.com/handbook/engineering/engineering-comms/>
3. Atlassian — *How to run a blameless postmortem*: <https://www.atlassian.com/incident-management/postmortem/blameless>
4. Google SRE Workbook — *Incident Response* (roles, comms lead, cadence): <https://sre.google/workbook/incident-response/>
5. Spike — *What is a War Room? How DevOps & SREs Use It* (dedicated channel, comms owner, 15-min cadence): <https://spike.sh/blog/what-is-a-war-room/>
6. Google re:Work — *Understand team effectiveness* (Project Aristotle; psychological safety): <https://rework.withgoogle.com/intl/en/guides/understand-team-effectiveness>
7. Tufin — *Least Privilege vs Need to Know in Cybersecurity*: <https://www.tufin.com/blog/least-privilege-vs-need-to-know-cybersecurity>
8. Cloudflare Learning — *What is the principle of least privilege?*: <https://www.cloudflare.com/learning/access-management/principle-of-least-privilege/>
9. Umbrex — *RACI Matrix (Responsible, Accountable, Consulted, Informed)*: <https://umbrex.com/resources/frameworks/organization-frameworks/raci-matrix-responsible-accountable-consulted-informed/>
10. Range — *Asynchronous Daily Standups: The Pros & Cons*: <https://www.range.co/blog/asynchronous-daily-standups>
11. Atlassian — *Why Asynchronous Video is Ideal for Weekly Team Updates*: <https://www.atlassian.com/blog/loom/weekly-updates>
12. Get Lighthouse — *5 Key Lessons from Camille Fournier's "The Manager's Path"* (1:1s as essential maintenance): <https://getlighthouse.com/blog/camille-fournier-lessons-managers-path/>
13. Umbrex — *Team Topologies* (team types, interaction modes, cognitive load): <https://umbrex.com/resources/frameworks/organization-frameworks/team-topologies/>
14. Umbrex — *Conway's Law* (systems mirror communication structures): <https://umbrex.com/resources/frameworks/organization-frameworks/conways-law/>
15. Slack — *5 ways to overcome information overload in the workplace*: <https://slack.com/blog/productivity/overcoming-information-overload-in-the-workplace>
16. Float — *Signal vs. noise: communicating effectively in a remote async team*: <https://www.float.com/blog/communicate-effectively-remote-async>

### Sources (Atlas system)

- `atlas/conversation/orchestrator.py` — the live pipeline (gate → route → group → ask-with-intent → owner decides → HITL → finalize).
- `atlas/cron/simulator.py` — autonomous goal generation, balanced across departments.
- `atlas/bus/router.py` — the single message chokepoint; org-scope gate; metrics emission.
- `atlas/org/generator.py` — the 100-agent hierarchy, teams, projects, clearance, goals.
- `atlas/org/ext_models.py` — `Intent`, `Sensitivity`, `Scope`, `ShareOutcome`, `Metrics`.
- `atlas/llm/base.py`, `atlas/llm/bedrock_provider.py` — the LLM seam (Mistral on Amazon Bedrock), including `decide_share` and the Policy Officer's `review_share`.
- `atlas/metrics/collector.py` — communication-efficiency counters.

---

## 2. How humans communicate in software orgs (synthesised)

**Async-first, with deliberate sync.** Modern distributed engineering orgs bias toward
asynchronous communication and a "handbook-first" single source of truth: GitLab
explicitly tells employees to *look it up in the handbook* before pinging a colleague,
and treats Slack as "busy but without the pressure of an immediate reply"
([GitLab async][1], [GitLab eng-comms][2]). Sync is reserved for what genuinely needs it
(ambiguity, conflict, relationship-building, leadership direction). The reason is
practical: async messages must carry enough self-contained context to be acted on without
a live back-and-forth ([Float][16]).

**Standups are a recurring status ritual, increasingly async.** The point of a standup is
a regular pulse — what I did, what I'm doing, what's blocking me — to give the team a
shared picture and managers visibility without "hounding folks" ([Range][10]). Many teams
run these asynchronously (written check-ins, weekly video updates) precisely so the
information is durable and searchable ([Atlassian weekly updates][11]).

**Incident communication is role-structured and cadenced.** During a real incident, orgs
spin up a war room / incident channel with explicit roles — an incident lead, domain
experts, and a dedicated **communications owner** — and a fixed update cadence (commonly
every ~15 minutes), keeping stakeholders informed without interrupting the responders
([Google SRE][4], [Spike war room][5]). Afterwards, the **blameless postmortem** asks
"what allowed this?" rather than "who did this?", because people only tell you what really
happened when they feel safe ([Atlassian blameless][3]).

**Confidentiality runs on need-to-know + least privilege.** Companies don't share
sensitive information broadly; access is granted on a *need-to-know* basis tied to a
**legitimate reason**, with least-privilege controls limiting exposure and reducing insider
risk ([Tufin][7], [Cloudflare][8]). The two principles compose: need-to-know governs *when*
someone has a legitimate reason; least privilege governs *how much* they can then see.

**Decision rights and escalation are explicit.** RACI gives a shared language for "who does
what and who decides": the **Accountable** person is the decision-maker and the escalation
point — the definitive answer when a question stalls — and disagreements escalate **up a
documented path** to that owner ([RACI][9]).

**1:1s and group settings serve different jobs.** Regular manager↔report 1:1s are
"like oil changes" — the channel for coaching, feedback, and hard conversations that group
meetings can't hold ([The Manager's Path][12]). Group/team forums exist for coordination
and alignment; choosing the right one (and the right channel) keeps communication from
fragmenting ([Float][16]).

**Cross-functional work is its own mode.** *Team Topologies* frames collaboration as a few
explicit interaction modes — temporary **collaboration** for discovery, **X-as-a-Service**
for steady state, **facilitating** for uplift — across cross-functional, stream-aligned
teams, while managing each team's **cognitive load** ([Team Topologies][13]). Conway's Law
adds that the system you ship mirrors your communication structure ([Conway][14]).

**Context/intent in messages is a discipline.** Good async messages lead with context,
state the ask/decision clearly, and make explicit *what you want from the reader* — so the
recipient knows what's expected and you avoid a follow-up loop ([Float][16]).

**Information overload is the dominant failure mode.** The lived reality is *too much*
signal, not too little: a majority of professionals say constant notifications make it hard
to focus, and knowledge workers spend large fractions of the week just juggling channels
and written messages ([Slack][15]). Good communication is therefore as much about *not*
contacting people as about contacting them.

**Psychological safety is the substrate.** Google's Project Aristotle found psychological
safety — a shared belief that the team is safe for interpersonal risk-taking
(Edmondson) — to be the top predictor of team effectiveness ([Google re:Work][6]).

---

## 3. Evaluation rubric

Criteria derived from the research above. Each is rated **Strong / Partial / Weak** with a
1–5 score and an explicit gap.

| # | Criterion | What it tests |
|---|---|---|
| 1 | Routing to the right person | Does the message reach the person who actually owns the answer? |
| 2 | Need-to-know & confidentiality | Is sensitive info gated on legitimate need, with redaction/denial? |
| 3 | Intent / context in messages | Does each message carry a motivation and stated purpose? |
| 4 | 1:1 vs group appropriateness | Are solo asks and group coordination chosen sensibly? |
| 5 | Escalation & human-in-the-loop | Do hard calls go up a path / to a human, like RACI escalation? |
| 6 | Asynchronicity & status cadence | Async habits, deferral, recurring standups, durable updates? |
| 7 | Efficiency / avoiding redundant contacts | Does it avoid needless pings (the real overload problem)? |
| 8 | Cross-functional reach | Coordination across departments, not just within one team? |
| 9 | Tone & psychological safety | Authored, human-toned messages; safe-to-ask framing? |
| 10 | Information-overload realism | Does it reflect the lived noise of real orgs, or only the ideal? |

---

## 4. Per-criterion evaluation of Atlas

### 4.1 Routing to the right person — **Strong (5/5)**

**Humans:** messages should reach the Accountable owner of a topic ([RACI][9]); in practice
people use directories, org knowledge, and "who owns X" intuition.

**Atlas:** routing is genuinely LLM-driven. `run_user_prompt` passes the **entire company
directory — all 100 agent cards** (id, name, role, dept, level, skills) — to Mistral, which
picks the owner (`orchestrator.py:148-170`, directory built in `_agent_directory`
`:710-722`). A deterministic skill-scorer (`router.route_prompt`) survives only as a fallback
when the LLM is unavailable (`:166-167`). Seniority is encoded so execution prompts route to
ICs and strategy prompts route up (`generator.py:_skills_for` `:81-106`). Bare greetings
correctly shortcut to the CEO for a friendly reply (`:152-155`).

**Gap:** routing picks a *single* best owner; real questions sometimes fan out to several
plausible owners or get redirected ("not me — ask X"). Minor, and arguably a feature for a
demonstrator.

### 4.2 Need-to-know & confidentiality — **Strong (5/5)**

**Humans:** access is granted on legitimate need-to-know, least-privilege, to reduce insider
exposure ([Tufin][7], [Cloudflare][8]).

**Atlas:** this is Atlas's strongest fidelity. Knowledge is modelled as `ContextItem`s with
explicit **sensitivity tiers** (public → internal → confidential → restricted → secret) and a
**scope** (org/project/team/role/private) plus `min_clearance` (`ext_models.py:50-76, 147-159`).
The **owner agent itself decides** whether to share its own data — Mistral returns
SHARE / REDACT / DENY / ESCALATE weighing the requester's role, clearance, teams/projects and
their stated reason (`orchestrator._decide_share` `:678-703`; provider prompt in
`bedrock_provider.py`). REDACT delivers a safe `redacted_summary` rather than the raw body
(`_build_llm_decision` `:62-73`; `_apply_decision` `:441-447`), and a SHARE remembers the fact
so it is not re-requested. This is a faithful, well-layered model of organisational
confidentiality — better than most demos, which have no sensitivity model at all.

**Gap:** the *selection* of which context is "needed" is shallow — `_identify_needs`
(`:317-329`) is deterministic token overlap between the prompt and an item's `topic_tags`, not
a reasoned judgement of what the task actually requires. So the **gating** of sensitive data is
sophisticated, but the **detection** of relevance that triggers a request is keyword-level.

### 4.3 Intent / context in messages — **Strong (4/5)**

**Humans:** lead with context and state what you want from the reader ([Float][16]).

**Atlas:** every agent→agent request carries an `Intent` — a natural-language `motivation`
("why I'm asking"), a `purpose_tag` (task-context / handoff / incident / planning / status /
social), the `requested_topic`, and a `declared_scope` (`ext_models.py:162-169`;
`build_request_intent` attaches it at `orchestrator.py:385`). The router stamps it onto the
message as the need-to-know extension and surfaces it to the UI as an `IntentView`
(`router.py:191-199`), and the owner's decision reads it. This is exactly the
"messages carry their motivation" discipline the research prescribes, and it is structural,
not incidental.

**Gap:** the *spoken* prose is authored well, but the structured intent fields for replies and
coordination are sometimes generic (`coordination_intent(topic)` for manager/group openers),
and `requested_topic` derives from a 4-token slice of the prompt (`_topic` `:724-726`). The
intent is always present (strong) but not always richly specific (hence 4, not 5).

### 4.4 1:1 vs group appropriateness — **Partial (3/5)**

**Humans:** 1:1s carry coaching/feedback/hard conversations ([Manager's Path][12]); group
forums carry coordination/alignment; pick deliberately ([Float][16]).

**Atlas:** the **decision** to coordinate as a group is LLM-made and constrained to the agent's
**real team roster** — `_decide_group` asks Mistral which teammates to pull in and keeps only
valid roster ids, never inventing people (`orchestrator.py:334-361`). Solo sourcing runs 1:1
threads (`_gather_individual` `:364-409`); group sessions run an opening + member replies +
a context exchange (`_run_group` `:529-569`). The 1:1-vs-group *choice* is therefore realistic.

**Gaps:** (a) the manager 1:1 path (`_consult_manager` `:502-526`) is a single fixed
question→answer round-trip, not the recurring coaching channel the literature describes;
(b) group structure is scripted — exactly one opening, one reply per member **in sorted id
order**, and one context exchange — with no clarifying questions, disagreement, or threading;
(c) grouping is **intra-team only** (`agent.profile.teams[0]`, `:341`), which understates how
often real coordination is cross-functional (see §4.8).

### 4.5 Escalation & human-in-the-loop — **Strong (4/5)**

**Humans:** hard calls escalate **up a documented path** to the Accountable owner ([RACI][9]);
sensitive decisions get a second pair of eyes.

**Atlas (what runs):** when the owner's LLM returns ESCALATE — or when the LLM is unreachable —
the share is handed to a **human operator** via a real HITL queue; the task enters
`INPUT_REQUIRED`, waits for the operator, and resolves as approve/redact/deny
(`_handle_hitl` `:453-500`; `HitlRequest` in `ext_models.py:215-233`). A genuine
human-in-the-loop on sensitive shares is a strong, realistic touch that most agent demos lack.

**Two pairs of eyes — the independent "Policy Officer" is wired in.** The Security
department head doubles as an independent **Policy Officer** that gives a compliance
**second opinion** on every owner SHARE/REDACT. `_decide_share` builds the owner's decision
and passes it to `_policy_review`, which calls the Security head's own LLM
(`llm.review_share`, declared in `llm/base.py` and implemented against Bedrock in
`bedrock_provider.py`); the officer may **concur or tighten** (redact / escalate / deny) but
never loosen. An override re-stamps the `ShareDecision` with `rule_id="POLICY-OFFICER"`, and
both concur and override emit a `policy_review` trace span on the officer; `policy_reviews` /
`policy_overrides` are metered (`metrics/collector.py`, surfaced as the UI "Compliance" tile),
and the tests `test_policy_officer_tightens_the_owners_share` / `test_policy_officer_cannot_loosen`
prove the tighten-only behaviour. This delivers the "two pairs of eyes" / segregation-of-duties
property real security functions rely on, and it stays fully LLM-driven (two independent agents
— owner + officer). (When the LLM is unreachable the offline path is "escalate to the human,"
not a deterministic matrix — `_decide_share` in `orchestrator.py`; the former `atlas/policy/`
rule matrix has been removed from the codebase.)

**Gap:** escalation goes to a **single global `operator`**, not *up the reporting chain* to the
Accountable manager/dept-head the way RACI prescribes — Atlas models "escalate to a human" but
not "escalate to the *right* human." Rating reflects the real HITL strength plus the now-wired
compliance second opinion, minus the missing chain-aware escalation.

### 4.6 Asynchronicity & status cadence — **Weak (2/5)**

**Humans:** async-first, handbook-first, "look it up before you ask," durable searchable
updates, deferred replies ([GitLab async][1], [GitLab eng-comms][2]); standups are a
**recurring** pulse ([Range][10], [Atlassian weekly updates][11]).

**Atlas:** conversations are essentially **synchronous request→reply chains**. In
`_gather_individual` and `_run_group`, the owner/members reply inline after a short
`_pause` (`:392-408`, `:553-565`); there is no deferral, no "I'll follow up," no
look-it-up-first, no durable knowledge base an agent consults before pinging. The cron
"standup"/"sync" goals (`simulator.py:DEPT_GOALS`) are **one-shot** events fired across a 15s
burst or a fixed loop (`simulator.py:154-209`), not a recurring daily/weekly ritual with
memory across days. There *is* a faint async-shaped seam — messages can be **omitted** when the
LLM can't author them (`_say` `:642-652`) — but that's a degradation path, not modelled
asynchrony.

**Gap:** the single biggest realism gap. Real engineering communication is dominated by async
patterns and durable artifacts; Atlas is a turn-by-turn synchronous simulator.

### 4.7 Efficiency / avoiding redundant contacts — **Strong (4/5)**

**Humans:** the goal is to *not* over-contact people; redundant pings are the overload problem
([Slack][15]).

**Atlas:** Atlas explicitly optimises against redundancy. If the requester already holds an
item at sufficient fidelity, the contact is **skipped** and counted as
`redundant_contacts_avoided` with a `CONTEXT_REUSED` event (`_gather_individual` `:372-383`;
`metrics/collector.py:85-87`). Agents `remember` shared facts (`LearnedFact`) so the same item
isn't re-requested. The Router meters hops, messages, distinct agents contacted,
shared/redacted/denied, and redundant-avoided at the single chokepoint (`router.py:207-227`;
`collector.py`), and the cron path load-sheds when too many scenarios are in flight
(`orchestrator.run_cron_task` `:200-206`). This directly models communication *efficiency*.

**Gap:** efficiency is measured as raw counts (fewer messages = better); it doesn't capture the
human trade-off where *too few* contacts means missing context, nor the cost of interrupting a
busy recipient. Still, this is a strong, well-instrumented fidelity point.

### 4.8 Cross-functional reach — **Partial (3/5)**

**Humans:** much real work is cross-functional — eng + design + product + QA on a launch — with
explicit interaction modes ([Team Topologies][13]); the system mirrors the comms structure
([Conway][14]).

**Atlas:** cross-functional reach happens **only via 1:1 sourcing**. The router can route a
prompt to any of the 100 agents regardless of department, and `_gather_individual` can ask an
owner in another department for a `ContextItem` (`:364-409`) — so a Sales handoff can pull an
Engineering or Data item. That is genuine cross-functional *information flow*. But
**group coordination is locked to a single own-team roster** (`_decide_group` uses
`agent.profile.teams[0]`, `:341`), so multi-discipline *coordination* (a launch war room
spanning departments) is never assembled. Projects (`atlas-core`, `billing`, `mobile`) span
departments in the data model (`generator.py:204-216`) but aren't used to form cross-functional
groups.

**Gap:** Atlas models cross-functional *asking* but not cross-functional *coordinating* — the
interaction mode the research treats as central.

### 4.9 Tone & psychological safety — **Partial (3/5)**

**Humans:** psychological safety — safe to ask, admit fallibility, ask lots of questions — is
the top driver of team effectiveness ([Google re:Work][6]); blameless framing replaces
"who did this?" with "what allowed this?" ([Atlassian blameless][3]).

**Atlas:** tone is a real strength in one respect: **every** message is authored by Mistral with
a brief preceding "thought" (`_think` / `_say` / `_send_say` `:629-676`), and there are **no
templates** — a message is genuine model prose or it is omitted. Greetings get a warm one-line
reply (`_run_greeting` `:289-314`). So messages read like people, not form letters, and the
owner-decides-with-a-reason pattern is courteous.

**Gaps:** safety is a *property of a relationship over time*, and Atlas conversations are
one-shot and shallow — agents never push back, disagree respectfully, admit a mistake, or ask
clarifying questions, which are the observable signals of psychological safety. The incident
goals (`simulator.py`) fire the share/HITL machinery but do **not** reproduce blameless-
postmortem structure (timeline, "what allowed this," follow-ups) or war-room roles
(incident lead / comms owner / cadence) from [Google SRE][4] and [Spike][5]. Tone is human;
the *interpersonal dynamics* that constitute safety are not modelled.

### 4.10 Information-overload realism — **Weak (2/5)**

**Humans:** the dominant lived experience is *overload* — notification fatigue, channel sprawl,
context-switching ([Slack][15]).

**Atlas:** Atlas models the **idealised** org, not the noisy one. It actively minimises contacts
(`redundant_contacts_avoided`, load-shedding) and paces LLM calls via a token bucket — all of
which reduce traffic. There is no notion of an overwhelmed recipient, no notification cost, no
"too many channels," no dropped/missed messages from overload. As an evaluation of *efficient*
communication this is intentional and fine; as a mirror of how humans *actually* experience
communication, it omits the defining friction.

**Gap:** by design Atlas shows best-case signal, not real-world noise. This is a reasonable
scope choice, but it is a realism gap worth naming.

---

## 5. Overall assessment

**Score summary**

| Criterion | Rating | Score |
|---|---|---|
| 1. Routing to the right person | Strong | 5 |
| 2. Need-to-know & confidentiality | Strong | 5 |
| 3. Intent / context in messages | Strong | 4 |
| 4. 1:1 vs group appropriateness | Partial | 3 |
| 5. Escalation & human-in-the-loop | Strong | 4 |
| 6. Asynchronicity & status cadence | Weak | 2 |
| 7. Efficiency / avoiding redundant contacts | Strong | 4 |
| 8. Cross-functional reach | Partial | 3 |
| 9. Tone & psychological safety | Partial | 3 |
| 10. Information-overload realism | Weak | 2 |
| **Overall** | **Partial–Strong** | **3.5 / 5** |

### Strengths (most human-realistic)

- **Need-to-know is genuinely well-modelled** — explicit sensitivity tiers and scopes, the
  *owner* decides on its own data, redaction returns a safe summary, and sensitive shares hit a
  real human-in-the-loop queue. This is closer to how confidentiality actually works in
  companies than virtually any agent demo.
- **An independent Policy Officer gives a compliance second opinion** — the Security head
  reviews every share and can tighten (never loosen) it, a "two pairs of eyes" /
  segregation-of-duties control, fully LLM-driven and traced.
- **Intent travels with every request** — a motivation + purpose tag + scope on each ask,
  exactly the "lead with context, say what you want" discipline of good async writing.
- **Routing is real and directory-wide**, and **efficiency is instrumented** at a single
  chokepoint with an explicit "don't re-contact people who already know" mechanism.
- **Messages are authored, never templated**, so the texture reads human.

### Biggest realism gaps

1. **Everything is synchronous and one-shot.** No async deferral, no durable
   handbook/knowledge base to consult before pinging, and "standups" are one-off bursts rather
   than a recurring cadence — the opposite of how modern distributed engineering orgs work
   ([GitLab][1], [Range][10]).
2. **Escalation isn't chain-aware.** HITL goes to one global operator, not *up the reporting
   line* to the Accountable owner, unlike RACI escalation ([RACI][9]).
3. **Coordination is intra-team only.** Cross-functional *information* flows, but cross-
   functional *coordination* (a launch/incident spanning eng+design+product) is never
   assembled, despite projects spanning departments in the data ([Team Topologies][13]).
4. **Conversations are scripted and shallow** — fixed opening + one reply per member, no
   clarifying questions, pushback, or follow-ups — which caps both incident realism and the
   interpersonal signals of psychological safety ([Atlassian blameless][3], [Google re:Work][6]).
5. **No information-overload reality** — Atlas models best-case signal, omitting the
   notification fatigue and channel sprawl that define real communication ([Slack][15]).

### Concrete recommendations

1. **(Done) The Policy Officer is now wired.** `_decide_share` calls `_policy_review`, routing
   the second opinion to the Security head (`snapshot.head_of(Department.SECURITY)`), recording
   `policy_reviews` / `policy_overrides` and emitting a `policy_review` trace span (UI
   "Compliance" tile). Natural next steps: let the officer *speak up* in-conversation on an
   override (a visible message, not just a trace span), and let it escalate contested shares to
   HITL rather than only tightening.
2. **Escalate up the chain, not to a global operator.** Resolve the HITL approver as the
   requester's (or owner's) `reports_to` / dept head before falling back to the operator —
   a small change in `_handle_hitl` that makes escalation match RACI.
3. **Add cross-functional coordination.** Let `_decide_group` optionally pull a small set of
   *project* members across departments (using `agent.profile.projects` and
   `snapshot.projects`), not just `teams[0]`, so launch/incident goals convene the disciplines
   that real ones do.
4. **Introduce a light async/cadence model.** Add an "agent consults its remembered facts /
   a shared knowledge item before contacting an owner" step (deepening the existing
   `redundant_contacts_avoided` path into a genuine look-it-up-first), and make cron standups
   recurring with day-over-day memory rather than one-shot.
5. **Deepen conversation shape for incidents.** For `incident`/`sec-incident` goals, add
   explicit war-room roles (incident lead, comms owner), a periodic status update, and a short
   blameless-postmortem closing ("timeline / what allowed this / follow-ups") — turning the
   current share-machinery firing into a recognisable incident conversation.
6. **Allow clarifying turns.** Let a recipient ask one clarifying question or respectfully
   defer/redirect before answering; even a single optional extra turn would make 1:1 and group
   exchanges read far more like real teams and surface psychological-safety behaviours.

---

*Method note:* ratings reflect the executed code paths in `atlas/conversation/orchestrator.py`
and its collaborators. The Policy Officer compliance review was wired into `_decide_share`
during the same work session in which this evaluation was produced; §4.5 and the score reflect
the wired behaviour (an earlier draft of this evaluation had caught it as dormant code, which
prompted the fix).

[1]: https://handbook.gitlab.com/handbook/company/culture/all-remote/asynchronous/
[2]: https://handbook.gitlab.com/handbook/engineering/engineering-comms/
[3]: https://www.atlassian.com/incident-management/postmortem/blameless
[4]: https://sre.google/workbook/incident-response/
[5]: https://spike.sh/blog/what-is-a-war-room/
[6]: https://rework.withgoogle.com/intl/en/guides/understand-team-effectiveness
[7]: https://www.tufin.com/blog/least-privilege-vs-need-to-know-cybersecurity
[8]: https://www.cloudflare.com/learning/access-management/principle-of-least-privilege/
[9]: https://umbrex.com/resources/frameworks/organization-frameworks/raci-matrix-responsible-accountable-consulted-informed/
[10]: https://www.range.co/blog/asynchronous-daily-standups
[11]: https://www.atlassian.com/blog/loom/weekly-updates
[12]: https://getlighthouse.com/blog/camille-fournier-lessons-managers-path/
[13]: https://umbrex.com/resources/frameworks/organization-frameworks/team-topologies/
[14]: https://umbrex.com/resources/frameworks/organization-frameworks/conways-law/
[15]: https://slack.com/blog/productivity/overcoming-information-overload-in-the-workplace
[16]: https://www.float.com/blog/communicate-effectively-remote-async
