"""Composition root — wires every backend component into one ``Runtime``.

Used by the FastAPI app (``atlas/main.py``) and by tests, so there's exactly one
place the dependency graph is assembled.
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
from atlas.hitl import HitlQueue
from atlas.llm import LLMProvider, get_provider
from atlas.metrics import MetricsCollector
from atlas.org.generator import OrgSnapshot, generate_org
from atlas.push import PushNotificationService
from atlas.trace import TraceCollector

if TYPE_CHECKING:
    from atlas.db import Database
    from atlas.db.writer import DbWriter
    from atlas.network.auth import NetworkService


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


def build_runtime(
    settings: Optional[Settings] = None,
    *,
    step_delay: Optional[float] = None,
    llm: Optional[LLMProvider] = None,
) -> Runtime:
    settings = settings or get_settings()
    snapshot = generate_org(settings.seed)
    broker = EventBroker()
    registry = AgentRegistry(snapshot, broker)
    discovery = Discovery(registry)
    metrics = MetricsCollector(broker)
    tasks: dict[str, Task] = {}
    router = Router(registry, discovery, broker, metrics, tasks)
    hitl = HitlQueue(broker)
    threads = ThreadStore()
    groups = GroupStore()
    trace = TraceCollector(broker)
    push = PushNotificationService(broker)
    db = None
    network = None
    dbwriter = None
    if settings.database_url:
        from atlas.db import Database  # lazy: only import SQLAlchemy when persistence is enabled
        from atlas.db.writer import DbWriter
        from atlas.network.auth import NetworkService

        db = Database(settings.database_url)
        dbwriter = DbWriter(db)
        network = NetworkService(db, broker, snapshot, session_ttl=settings.network_session_ttl_seconds)
    llm = llm if llm is not None else get_provider(settings, broker=broker)
    router.network = network  # enable the membership backstop at the chokepoint (None ⇒ off)
    # durable write-through at each point of record (None ⇒ persistence off, fully in-memory)
    router.dbwriter = dbwriter
    hitl.dbwriter = dbwriter
    push.dbwriter = dbwriter
    orchestrator = Orchestrator(
        snapshot=snapshot,
        registry=registry,
        router=router,
        broker=broker,
        metrics=metrics,
        hitl=hitl,
        threads=threads,
        groups=groups,
        llm=llm,
        trace=trace,
        hitl_timeout=settings.hitl_timeout_seconds,
        step_delay=0.45 if step_delay is None else step_delay,
        cron_max_inflight=settings.cron_max_inflight,
        network=network,
    )
    orchestrator.dbwriter = dbwriter
    if network is not None:
        network.on_join = orchestrator.resume_pending_auth  # resume auth-required tasks when an agent joins
    cron = CronSimulator(
        orchestrator=orchestrator, registry=registry, snapshot=snapshot, broker=broker, settings=settings
    )
    return Runtime(
        settings=settings,
        snapshot=snapshot,
        broker=broker,
        registry=registry,
        discovery=discovery,
        metrics=metrics,
        hitl=hitl,
        threads=threads,
        groups=groups,
        llm=llm,
        router=router,
        orchestrator=orchestrator,
        cron=cron,
        trace=trace,
        push=push,
        tasks=tasks,
        db=db,
        network=network,
        dbwriter=dbwriter,
    )
