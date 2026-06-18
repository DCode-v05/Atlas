"""Identifier and timestamp helpers.

Runtime ids (messages, tasks, contexts) are random UUIDs — they are not part of
any golden snapshot. *Agent* ids, by contrast, are deterministic slugs produced
by the org generator so the company is byte-reproducible from a seed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id(prefix: str = "") -> str:
    """A fresh random id, optionally prefixed (e.g. ``msg-``, ``task-``)."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)
