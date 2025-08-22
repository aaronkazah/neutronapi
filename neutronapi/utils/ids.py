"""
Time-sortable ID generators.

Provides compact, lexicographically sortable identifiers suitable for
use as primary keys across SQLite and PostgreSQL.

Defaults to ULID (26-char Crockford Base32), which is monotonic by
timestamp portion and widely used. If Python's uuid.uuid7 is available
(3.12+), you can opt to use it via generate_time_sortable_id(kind='uuid7').
"""
from __future__ import annotations

import os
import time
from typing import Literal


_CROCKFORD32 = "0123456789abcdefghjkmnpqrstvwxyz"


def ulid() -> str:
    """Generate a ULID string (26 chars, Crockford Base32).

    - First 48 bits are milliseconds since Unix epoch
    - Remaining 80 bits are randomness
    - Lexicographically sortable by creation time
    """
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand80 = int.from_bytes(os.urandom(10), "big")
    value = (ts_ms << 80) | rand80  # 128-bit integer

    # Encode to 26 Base32 chars (most significant group first)
    out = []
    for shift in range(125, -1, -5):  # 26 groups of 5 bits = 130 bits (top padded)
        index = (value >> shift) & 0x1F
        out.append(_CROCKFORD32[index])
    return "".join(out)


def generate_time_sortable_id(kind: Literal["ulid", "uuid7", "auto"] = "auto") -> str:
    """Generate a time-sortable ID string.

    - kind='ulid': always return ULID (26-char Base32)
    - kind='uuid7': return RFC 4122 UUIDv7 if available, else ULID
    - kind='auto' (default): prefer UUIDv7 when available, otherwise ULID
    """
    if kind in ("uuid7", "auto"):
        try:
            # Python 3.12+
            import uuid  # type: ignore

            if hasattr(uuid, "uuid7"):
                return str(uuid.uuid7()).lower()
        except Exception:
            pass
    return ulid()

