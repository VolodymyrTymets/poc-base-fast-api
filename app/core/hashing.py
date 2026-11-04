"""Argon2id hashing for secrets a user chooses or receives: sign-in codes (task 7.1) and, later, passwords (task 7.3). ADR-0028.

The salt and the cost parameters live inside the hash string, so a stored value is checked by itself and no salt column is
needed. Refresh and reset tokens are high-entropy, so they use a plain sha256 (`hash_token`, `token_matches`; ADR-0008, rule P5), not Argon2.

Hashing is CPU and memory heavy, so both functions run in a worker thread and never block the event loop. The `PasswordHash`
object holds no mutable state, so sharing it between threads is safe.
"""

import asyncio
import hashlib
import hmac
import logging

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

logger = logging.getLogger(__name__)

# OWASP's minimum Argon2id profile (19 MiB, 2 iterations, 1 lane), not the library default of 64 MiB: the sign-in code request
# is unauthenticated and not rate limited (issue I.8), so the memory one request costs is the amplification a flood gets.
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST_KIB = 19 * 1024
ARGON2_PARALLELISM = 1

_hasher = PasswordHash(
    (
        Argon2Hasher(
            time_cost=ARGON2_TIME_COST,
            memory_cost=ARGON2_MEMORY_COST_KIB,
            parallelism=ARGON2_PARALLELISM,
        ),
    )
)

# A valid Argon2id hash (same cost as `hash_secret`) of a value nobody sends: a check with nothing to match runs against it, so an unknown phone or
# email, a missing hash or an expired code cost about the same time as a wrong secret and the 401 does not tell which accounts exist.
DUMMY_HASH = "$argon2id$v=19$m=19456,t=2,p=1$much5sGO41ZuZ1RPLIa4eQ$WrkG3m+uQY4I7f754HVd4gVkq6L22XTF3jNs+sxWt0E"


async def hash_secret(secret: str) -> str:
    """The Argon2id hash of `secret`, with a fresh random salt: two calls on one secret differ."""
    return await asyncio.to_thread(_hasher.hash, secret)


async def verify_secret(secret: str, hashed: str) -> bool:
    """Whether `secret` matches `hashed`. A string that is not a hash this module can read verifies `False`."""
    try:
        return await asyncio.to_thread(_hasher.verify, secret, hashed)
    except UnknownHashError:
        # A corrupt stored value is a data problem worth a trace, but the value itself is never logged (rules D8, P4).
        logger.warning("a stored hash is not in a readable format")
        return False


def hash_token(token: str) -> str:
    """The sha256 of a refresh or reset token as 64 hex characters: what the database stores instead of the token (rule P5)."""
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str, stored: str | None) -> bool:
    """Whether `token` hashes to the `stored` value, in constant time; a missing stored value never matches."""
    if stored is None:
        return False
    return hmac.compare_digest(hash_token(token), stored)
