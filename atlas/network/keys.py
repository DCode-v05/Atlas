"""Ed25519 keypair + signature helpers for network authentication.

An agent proves its identity with an Ed25519 keypair (asymmetric — no static
shared secret). The network verifies a signed challenge against the agent's
stored **public** key, then issues a short-lived scoped JWT. These helpers wrap
the ``cryptography`` primitives in PEM strings so keys round-trip cleanly through
the database.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def generate_keypair() -> tuple[str, str]:
    """Return ``(private_pem, public_pem)`` for a fresh Ed25519 keypair."""
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        priv.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return priv_pem, pub_pem


def sign(private_pem: str, message: bytes) -> bytes:
    priv = serialization.load_pem_private_key(private_pem.encode(), password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    return priv.sign(message)


def verify(public_pem: str, message: bytes, signature: bytes) -> bool:
    pub = serialization.load_pem_public_key(public_pem.encode())
    assert isinstance(pub, Ed25519PublicKey)
    try:
        pub.verify(signature, message)
        return True
    except InvalidSignature:
        return False
