"""Versioned deterministic canonical encoding.

Rules (v1): UTF-8, sorted keys, compact separators, no floating point values, no NaN,
no implicit Unicode or whitespace normalisation.  Monetary values are integers;
decimal values use :func:`meridian.contracts.common.normalize_decimal_string`.
Signatures always live *outside* the signed payload.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel

from ..contracts.common import CANONICAL_ENCODING_VERSION, canonical_datetime


class CanonicalEncodingError(TypeError):
    """Raised when a value cannot be encoded deterministically."""


def to_canonical_value(value: Any) -> Any:
    """Recursively convert ``value`` to canonical JSON primitives."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalEncodingError(
            "floating point values are not allowed in canonical payloads"
        )
    if isinstance(value, datetime):
        return canonical_datetime(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalEncodingError("non-finite decimal in canonical payload")
        text = format(value.normalize(), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    if isinstance(value, Enum):
        return to_canonical_value(value.value)
    if isinstance(value, BaseModel):
        return {
            name: to_canonical_value(getattr(value, name))
            for name in type(value).model_fields
        }
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEncodingError("canonical payload keys must be strings")
            out[key] = to_canonical_value(item)
        return out
    if isinstance(value, (list, tuple)):
        return [to_canonical_value(item) for item in value]
    raise CanonicalEncodingError(f"unsupported canonical payload type: {type(value)!r}")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode ``value`` with the versioned canonical JSON rules."""

    canonical = to_canonical_value(value)
    return json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def canonical_hash_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


DOMAIN_LEAF = b"\x00"
DOMAIN_NODE = b"\x01"


def leaf_hash(payload: bytes) -> bytes:
    """``SHA256(0x00 || payload)`` (RFC 9162 leaf domain separation)."""

    return hashlib.sha256(DOMAIN_LEAF + payload).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    """``SHA256(0x01 || left || right)`` (RFC 9162 interior node)."""

    return hashlib.sha256(DOMAIN_NODE + left + right).digest()


def leaf_hash_hex(payload: bytes) -> str:
    return leaf_hash(payload).hex()


encoding_version = CANONICAL_ENCODING_VERSION
