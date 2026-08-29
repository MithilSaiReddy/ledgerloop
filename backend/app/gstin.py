"""GSTIN validation: structural regex + official mod-36 checksum."""

import re

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")

_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum_char(prefix14: str) -> str:
    """Compute the 15th (checksum) character for a 14-char GSTIN prefix."""
    total = 0
    for i, ch in enumerate(prefix14.upper()):
        value = _CHARSET.index(ch)
        factor = 1 if i % 2 == 0 else 2
        product = value * factor
        total += product // 36 + product % 36
    return _CHARSET[(36 - total % 36) % 36]


def gstin_valid(gstin: str | None) -> bool:
    if not gstin or not isinstance(gstin, str):
        return False
    g = gstin.strip().upper()
    if not GSTIN_RE.match(g):
        return False
    return gstin_checksum_char(g[:14]) == g[14]
