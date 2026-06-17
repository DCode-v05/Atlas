"""protocol — a small, readable, spec-faithful implementation of A2A (JSON-RPC binding).

This package is CORE A2A ONLY. The organisation-specific concepts (roles,
performatives, meetings, ledgers) live in the `org` package and ride on top of
A2A via `org.envelope`. Keeping them separate is deliberate: you can point
any real A2A client at an agent here and it will work.
"""
