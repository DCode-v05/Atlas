"""Multi-org federation — several sealed 100-agent organisations side by side.

Atlas's single-org model is a *private network*: 100 agents that talk freely
(detailed, unrestricted-about-the-org) through one in-process Router. A **federation**
runs N such private networks at once and lets them talk to each other **publicly** —
the way two real companies do. The rules mirror reality:

- **Inside an org**: full need-to-know sharing, the existing two-layer decision +
  Policy Engine. Nothing changes.
- **Between orgs**: only **PUBLIC** information may cross the boundary; everything
  internal/confidential/restricted/secret stays in the building. "Only the necessary
  things leave." This is enforced by the Policy Engine's ``CROSS-ORG-RESTRICT`` rule.

The boundary's integrity is structural, not a flag you must remember to set:

- Each org's Router only knows its own registry, so an org's agents *physically
  cannot* reach a peer except through the **gateway** (`FederationGateway`).
- The gateway is the **sole origin** of ``cross_org=True`` and the sole door between
  orgs — exactly as the Router is the one chokepoint inside an org.
- A cross-org request is decided by the **target** org's own machinery (its owner
  agent + its Policy Engine): it's their data, their floor.

See ``atlas/runtime.py`` (`build_federation`) for the composition root and
``gateway.py`` for the door.
"""

from __future__ import annotations

# A deterministic name table so each org has a stable, human identity. Index 0 is the
# canonical "atlas" org (so the single-org demo and N=1 federation are identical).
_ORG_NAMES: tuple[tuple[str, str], ...] = (
    ("atlas", "Atlas"),
    ("globex", "Globex"),
    ("initech", "Initech"),
    ("umbrella", "Umbrella"),
    ("hooli", "Hooli"),
    ("stark", "Stark Industries"),
    ("wayne", "Wayne Enterprises"),
    ("acme", "Acme"),
)


def org_specs(seed: int, count: int) -> list[tuple[str, str, int]]:
    """Deterministic ``(org_id, org_name, org_seed)`` for each org in a federation.

    Each org gets a distinct seed (``seed + index``) so its 100 agents — and their
    ``SEP-<16 digits>`` ids — are disjoint from every peer's. Same ``(seed, count)``
    ⇒ identical federation, every run.
    """
    count = max(1, count)
    specs: list[tuple[str, str, int]] = []
    for i in range(count):
        if i < len(_ORG_NAMES):
            oid, name = _ORG_NAMES[i]
        else:
            oid, name = f"org-{i}", f"Org {i}"
        specs.append((oid, name, seed + i))
    return specs


from atlas.federation.gateway import FederationGateway  # noqa: E402  (avoids a cycle)

__all__ = ["FederationGateway", "org_specs"]
