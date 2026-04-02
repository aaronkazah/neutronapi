"""Request ID generation."""

from __future__ import annotations

import os
import time


_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZabcdefghjkmnpqrstvwxyz"


def generate_request_id() -> str:
    """Generate a short, time-sortable request id."""
    ts = int(time.time() * 1000) & ((1 << 40) - 1)
    rand = int.from_bytes(os.urandom(6), "big")
    value = (ts << 48) | rand
    chars = []
    base = len(_ALPHABET)
    while value:
        chars.append(_ALPHABET[value % base])
        value //= base
    if not chars:
        chars.append(_ALPHABET[0])
    return "req_" + "".join(reversed(chars))
