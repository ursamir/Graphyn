# app/core/utils/hash.py
"""
Bounded Context:  Platform Infrastructure (shared by all BCs)
Responsibility:   Non-cryptographic stable hash utilities for deterministic
                  node seeds, export file IDs, and split group ordering.
Owns:             stable_hash() — MD5-based, JSON-serialised, cross-run stable.
Public Surface:   stable_hash(*args) → int
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not be used for security purposes (not cryptographic).
Dependencies:     stdlib (hashlib, json).
Reason To Change: Hash algorithm changes, or new hash utility functions added.

Uses MD5 for speed — NOT for security. The ``usedforsecurity=False`` flag
is required on FIPS-compliant systems where MD5 is otherwise blocked.
"""

import hashlib
import json


def stable_hash(*args) -> int:
    """Return a stable integer hash of the given arguments.

    Suitable for seeding random number generators and cache key derivation.
    Not suitable for security-sensitive purposes.

    Returns a non-negative integer in the range [0, 2^128).

    Uses JSON encoding to avoid separator-collision bugs: previously
    ``stable_hash("a|b", "c")`` and ``stable_hash("a", "b|c")`` produced
    the same hash because ``"|".join(...)`` is ambiguous when args contain
    the separator character. JSON encoding is unambiguous.

    ``None`` and ``"None"`` are also correctly distinguished because
    JSON encodes them as ``null`` and ``"None"`` respectively.

    Argument ORDER matters: ``stable_hash("a", "b") != stable_hash("b", "a")``.
    Dict KEY order within a single argument does NOT matter (``sort_keys=True``
    normalises dict key order before hashing).

    Only JSON-serialisable types are accepted (str, int, float, bool, None,
    list, dict).  Passing a non-serialisable object raises ``TypeError`` —
    this is intentional: ``default=str`` was removed because objects whose
    ``str()`` representation includes a memory address (e.g. ``<Foo object at
    0x7f...>``) would produce hashes that are NOT stable across process
    restarts, silently violating the function's core guarantee.
    """
    s = json.dumps(list(args), sort_keys=True)
    return int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest(), 16)
