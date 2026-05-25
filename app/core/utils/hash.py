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

    Uses JSON encoding to avoid separator-collision bugs: previously
    ``stable_hash("a|b", "c")`` and ``stable_hash("a", "b|c")`` produced
    the same hash because ``"|".join(...)`` is ambiguous when args contain
    the separator character. JSON encoding is unambiguous.

    ``None`` and ``"None"`` are also correctly distinguished because
    JSON encodes them as ``null`` and ``"None"`` respectively.
    """
    s = json.dumps(list(args), sort_keys=True, default=str)
    return int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest(), 16)
