"""Network authentication — Ed25519 keypair enrollment + scoped JWT sessions.

Agents authenticate to *join* the network once (a signed challenge → a short-lived
scoped JWT + a revocable DB session); thereafter they communicate freely without
re-authenticating, while the Policy Engine still authorises every message.
"""

from atlas.network.keys import generate_keypair, sign, verify

__all__ = ["generate_keypair", "sign", "verify"]
