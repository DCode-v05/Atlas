"""Atlas A2A extension URIs.

Per the A2A spec, the protocol stays generic and domain concepts attach via the
*extensions* mechanism rather than polluting core types. Atlas declares three:

- ``org-profile``   : agent identity (dept / role / level / reportsTo / clearance)
                      carried on the Agent Card.
- ``need-to-know``  : sensitivity + scope on context items, and the requester's
                      *intent* on messages — the inputs to the policy engine.
- ``coordination``  : group-session and HITL signalling on messages / tasks.
"""

from __future__ import annotations

ORG_PROFILE_EXT = "urn:atlas:ext:org-profile:v1"
NEED_TO_KNOW_EXT = "urn:atlas:ext:need-to-know:v1"
COORDINATION_EXT = "urn:atlas:ext:coordination:v1"

ALL_EXTENSIONS = (ORG_PROFILE_EXT, NEED_TO_KNOW_EXT, COORDINATION_EXT)
