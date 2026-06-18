"""Lightweight stores for conversation state.

Per-agent *memory* lives on each ``OrgAgent`` (owned items + learned facts);
these stores hold the *conversation* structure — the 1:1 threads and group
sessions, keyed for reuse so the same pair/team doesn't spin up duplicates
within one context.
"""

from __future__ import annotations

from atlas.org.ext_models import GroupSession, Thread


class ThreadStore:
    def __init__(self) -> None:
        self.threads: dict[str, Thread] = {}
        self._by_pair: dict[tuple[str, frozenset[str]], Thread] = {}

    def get_or_create(
        self, context_id: str, a: str, b: str, *, topic: str = "", task_id: str | None = None
    ) -> tuple[Thread, bool]:
        key = (context_id, frozenset((a, b)))
        existing = self._by_pair.get(key)
        if existing is not None:
            return existing, False
        thread = Thread(context_id=context_id, participants=[a, b], topic=topic, task_id=task_id)
        self.threads[thread.thread_id] = thread
        self._by_pair[key] = thread
        return thread, True

    def get(self, thread_id: str) -> Thread | None:
        return self.threads.get(thread_id)


class GroupStore:
    def __init__(self) -> None:
        self.groups: dict[str, GroupSession] = {}

    def create(
        self, context_id: str, team_id: str, topic: str, members: list[str], initiator: str
    ) -> GroupSession:
        group = GroupSession(
            context_id=context_id, team_id=team_id, topic=topic, members=members, initiator=initiator
        )
        self.groups[group.group_id] = group
        return group

    def get(self, group_id: str) -> GroupSession | None:
        return self.groups.get(group_id)
