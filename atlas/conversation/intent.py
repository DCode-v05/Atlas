"""Intent construction — the *motivation* attached to every request.

Intent is not cosmetic: ``purpose_tag`` and ``declared_scope`` are read by the
policy engine, so the reason an agent gives changes what it's allowed to receive.
"""

from __future__ import annotations

from typing import Optional

from atlas.org.ext_models import ContextItem, Intent, OrgProfile, PurposeTag, Scope


def build_request_intent(
    requester: OrgProfile,
    item: ContextItem,
    *,
    task_ref: Optional[str] = None,
    purpose: PurposeTag = PurposeTag.TASK_CONTEXT,
    declared_scope: Optional[Scope] = None,
    motivation: Optional[str] = None,
) -> Intent:
    ds = declared_scope or item.scope
    if motivation is None:
        motivation = (
            f"I'm working on a task that needs '{item.title}' to make progress, "
            f"so I'm requesting it within my {ds.value} scope."
        )
    return Intent(
        motivation=motivation,
        purpose_tag=purpose,
        requested_topic=item.title,
        declared_scope=ds,
        task_ref=task_ref,
    )


def coordination_intent(topic: str, scope: Scope = Scope.TEAM) -> Intent:
    return Intent(
        motivation=f"Let's align as a team on {topic}.",
        purpose_tag=PurposeTag.PLANNING,
        requested_topic=topic,
        declared_scope=scope,
    )
