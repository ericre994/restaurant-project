"""Password hashing + session-token primitives — stdlib only (no passlib/bcrypt
or JWT dependency), which suits the local prototype and keeps installs light.

Passwords use PBKDF2-HMAC-SHA256 with a per-password random salt, stored as a
self-describing string `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>` so the
parameters travel with the hash and can be raised later without a migration.
Real production auth (managed provider) is still an open decision (TDD §9); this
is a self-contained local implementation, not that decision.
"""
import base64
import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000  # OWASP-ish floor for PBKDF2-SHA256; fine for a prototype
_SALT_BYTES = 16
_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify against a stored hash string. False (not an error) on
    any malformed/None hash so a passwordless account can never be logged into."""
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        expected = _unb64(hash_b64)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _unb64(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, expected)
    except (AttributeError, ValueError, TypeError):
        return False


def new_token() -> str:
    """A URL-safe opaque session token with ~256 bits of entropy."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))
