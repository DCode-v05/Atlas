"""Composition root — wires every backend component into one ``Runtime``.

Used by the FastAPI app (``atlas/main.py``) and by tests, so there's exactly one
place the dependency graph is assembled.

Two entry points share the same wiring:

- ``build_runtime`` — the single-org demo (one private network of 100 agents). This is
  the N=1 case and returns the historical ``Runtime`` unchanged.
- ``build_federation`` — N sealed organisations sharing one set of cross-cutting
  singletons (broker, llm, hitl, trace, push, metrics, db), each with its own registry /
  router / network / orchestrator / cron, joined by a ``FederationGateway``. Between
  orgs, only PUBLIC information may cross (see ``atlas/federation``).

The shared/per-org split is the federation's design: the things a federation has ONE of
(the SSE stream, the model, the operator's HITL queue, the trace + metrics, the DB) are
built once and handed to every org; the things each org has its OWN of (its agents, its
in-process bus, its membership, its conversation engine) are built per org and sealed —
an org's Router only knows its own agents, so orgs can reach each other ONLY through the
gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from atlas.a2a.models import Task
from atlas.bus import AgentRegistry, Discovery, Router
from atlas.config import Settings, get_settings
from atlas.conversation import GroupStore, Orchestrator, ThreadStore
from atlas.cron import CronSimulator
from atlas.events import EventBroker
from atlas.federation import FederationGateway, org_specs
from atlas.hitl import HitlQueue
from atlas.llm import LLMProvider, get_provider
from atlas.metrics import MetricsCollector
from atlas.org.company import company_for
from atlas.org.generator import OrgSnapshot, generate_org
from atlas.push import PushNotificationService
from atlas.trace import TraceCollector

if TYPE_CHECKING:
    from atlas.db import Database
    from atlas.db.writer import DbWriter
    from atlas.network.auth import NetworkService


@dataclass
class Shared:
    """The cross-cutting singletons a federation (or a lone org) has exactly one of."""

    settings: Settings
    broker: EventBroker
    metrics: MetricsCollector
    hitl: HitlQueue
    trace: TraceCollector
    push: PushNotificationService
    llm: LLMProvider
    db: "Optional[Database]" = None
    dbwriter: "Optional[DbWriter]" = None


@dataclass
class OrgRuntime:
    """One sealed organisation — a private network of 100 agents with its own bus."""

    org_id: str
    org_name: str
    snapshot: OrgSnapshot
    registry: AgentRegistry
    discovery: Discovery
    router: Router
    threads: ThreadStore
    groups: GroupStore
    tasks: dict[str, Task]
    orchestrator: Orchestrator
    cron: CronSimulator
    network: "Optional[NetworkService]" = None


@dataclass
class Runtime:
    settings: Settings
    snapshot: OrgSnapshot
    broker: EventBroker
    registry: AgentRegistry
    discovery: Discovery
    metrics: MetricsCollector
    hitl: HitlQueue
    threads: ThreadStore
    groups: GroupStore
    llm: LLMProvider
    router: Router
    orchestrator: Orchestrator
    cron: CronSimulator
    trace: TraceCollector
    push: PushNotificationService
    tasks: dict[str, Task]
    db: "Optional[Database]" = None
    network: "Optional[NetworkService]" = None
    dbwriter: "Optional[DbWriter]" = None


@dataclass
class Federation:
    """N sealed organisations + the gateway that lets them talk publicly."""

    shared: Shared
    orgs: "dict[str, OrgRuntime]"
    gateway: FederationGateway

    @property
    def settings(self) -> Settings:
        return self.shared.settings

    @property
    def broker(self) -> EventBroker:
        return self.shared.broker

    @property
    def primary(self) -> OrgRuntime:
        """The first org — the one flattened to ``app.state.runtime`` so every existing
        route/test keeps working as the single-org demo."""
        return next(iter(self.orgs.values()))

    def runtime_for(self, org_id: str) -> Runtime:
        """A flat ``Runtime`` view onto one org — lets routes serve any org with the same
        view-builders they use for the primary one."""
        return _runtime_from(self.shared, self.orgs[org_id])


def _build_shared(
    settings: Settings, *, llm: Optional[LLMProvider] = None
) -> Shared:
    """Build the singletons shared across every org in the (possibly N=1) federation."""
    broker = EventBroker()
    metrics = MetricsCollector(broker)
    hitl = HitlQueue(broker)
    trace = TraceCollector(broker)
    push = PushNotificationService(broker)
    db = None
    dbwriter = None
    if settings.database_url:
        from atlas.db import Database  # lazy: only import SQLAlchemy when persistence is enabled
        from atlas.db.writer import DbWriter

        db = Database(settings.database_url)
        dbwriter = DbWriter(db)
    llm = llm if llm is not None else get_provider(settings, broker=broker)
    # durable write-through at each shared point of record (None ⇒ persistence off)
    hitl.dbwriter = dbwriter
    push.dbwriter = dbwriter
    return Shared(
        settings=settings, broker=broker, metrics=metrics, hitl=hitl, trace=trace,
        push=push, llm=llm, db=db, dbwriter=dbwriter,
    )


def build_org_runtime(
    shared: Shared, *, seed: int, org_id: str, org_name: str, step_delay: Optional[float] = None, company=None,
) -> OrgRuntime:
    """Wire ONE sealed organisation onto the shared singletons. The org's Router only ever
    knows this org's registry — the structural guarantee that an org cannot reach a peer
    except through the federation gateway. ``company`` makes a peer org a different company
    (projects/people/secrets); None ⇒ the canonical atlas company."""
    settings = shared.settings
    snapshot = generate_org(seed, org_id=org_id, org_name=org_name, company=company)
    registry = AgentRegistry(snapshot, shared.broker)
    discovery = Discovery(registry)
    tasks: dict[str, Task] = {}
    router = Router(registry, discovery, shared.broker, shared.metrics, tasks)
    threads = ThreadStore()
    groups = GroupStore()
    network = None
    if shared.db is not None:
        from atlas.network.auth import NetworkService

        network = NetworkService(
            shared.db, shared.broker, snapshot, session_ttl=settings.network_session_ttl_seconds
        )
    router.network = network  # membership backstop at the chokepoint (None ⇒ off)
    router.dbwriter = shared.dbwriter
    orchestrator = Orchestrator(
        snapshot=snapshot,
        registry=registry,
        router=router,
        broker=shared.broker,
        metrics=shared.metrics,
        hitl=shared.hitl,
        threads=threads,
        groups=groups,
        llm=shared.llm,
        trace=shared.trace,
        hitl_timeout=settings.hitl_timeout_seconds,
        step_delay=0.45 if step_delay is None else step_delay,
        cron_max_inflight=settings.cron_max_inflight,
        network=network,
    )
    orchestrator.dbwriter = shared.dbwriter
    if network is not None:
        network.on_join = orchestrator.resume_pending_auth  # resume auth-required tasks on join
    cron = CronSimulator(
        orchestrator=orchestrator, registry=registry, snapshot=snapshot,
        broker=shared.broker, settings=settings,
    )
    return OrgRuntime(
        org_id=org_id, org_name=org_name, snapshot=snapshot, registry=registry,
        discovery=discovery, router=router, threads=threads, groups=groups, tasks=tasks,
        orchestrator=orchestrator, cron=cron, network=network,
    )


def _runtime_from(shared: Shared, org: OrgRuntime) -> Runtime:
    """Flatten a (shared, org) pair into the historical flat ``Runtime`` — keeps the API and
    the 100+ tests that read ``runtime.<field>`` working unchanged."""
    return Runtime(
        settings=shared.settings, snapshot=org.snapshot, broker=shared.broker,
        registry=org.registry, discovery=org.discovery, metrics=shared.metrics,
        hitl=shared.hitl, threads=org.threads, groups=org.groups, llm=shared.llm,
        router=org.router, orchestrator=org.orchestrator, cron=org.cron, trace=shared.trace,
        push=shared.push, tasks=org.tasks, db=shared.db, network=org.network, dbwriter=shared.dbwriter,
    )


def build_runtime(
    settings: Optional[Settings] = None,
    *,
    step_delay: Optional[float] = None,
    llm: Optional[LLMProvider] = None,
) -> Runtime:
    """The single-org demo (N=1). Builds the shared singletons and one ``atlas`` org, and
    returns the historical flat ``Runtime``."""
    settings = settings or get_settings()
    shared = _build_shared(settings, llm=llm)
    org = build_org_runtime(
        shared, seed=settings.seed, org_id="atlas", org_name="Atlas", step_delay=step_delay
    )
    return _runtime_from(shared, org)


def build_federation(
    settings: Optional[Settings] = None,
    *,
    step_delay: Optional[float] = None,
    llm: Optional[LLMProvider] = None,
) -> Federation:
    """Build a federation of ``settings.org_count`` sealed organisations sharing one set of
    singletons, joined by a ``FederationGateway``. ``org_count == 1`` yields a one-org
    federation whose single org is byte-identical to ``build_runtime()``'s."""
    settings = settings or get_settings()
    shared = _build_shared(settings, llm=llm)
    orgs: dict[str, OrgRuntime] = {}
    for index, (org_id, org_name, seed) in enumerate(org_specs(settings.seed, settings.org_count)):
        orgs[org_id] = build_org_runtime(
            shared, seed=seed, org_id=org_id, org_name=org_name, step_delay=step_delay,
            company=company_for(org_id, index),  # index 0 / atlas ⇒ canonical; peers ⇒ distinct companies
        )
    gateway = FederationGateway(orgs)
    for org in orgs.values():
        org.orchestrator.federation = gateway  # the door each org reaches its peers through
    return Federation(shared=shared, orgs=orgs, gateway=gateway)
