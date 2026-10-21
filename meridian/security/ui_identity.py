"""Verify short-lived, server-signed UI identities before deriving permissions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from uuid import UUID

from meridian.security.auth import AuthenticationError, Permission, Principal, Role


def authenticate_ui_token(token: str) -> Principal:
    try:
        if len(token) > 4096:
            raise ValueError()
        prefix, payload, signature = token.split(".")
        if prefix != "ui1" or not re.fullmatch(r"[A-Za-z0-9_-]+", payload):
            raise ValueError()
        root = Path(__file__).resolve().parents[2]
        key_path = root / (os.environ.get("UI_AUTH_KEY_PATH") or "runtime/auth-bridge/key")
        key = key_path.read_bytes()
        if len(key) != 32:
            raise ValueError()
        expected = base64.urlsafe_b64encode(
            hmac.digest(key, f"ui1.{payload}".encode(), hashlib.sha256)
        ).decode().rstrip("=")
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if set(claims) != {
            "v", "sub", "username", "role", "offices", "restricted", "office",
            "tenant", "iat", "exp",
        }:
            raise ValueError()
        if not isinstance(claims["sub"], str):
            raise ValueError()
        UUID(claims["sub"])
        if (
            type(claims["v"]) is not int or claims["v"] != 1
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", claims["username"])
        ):
            raise ValueError()
        role = Role(claims["role"])
        if role not in {Role.ADMIN, Role.REVIEWER, Role.UPLOADER, Role.READER}:
            raise ValueError()
        offices = claims["offices"]
        if (
            not isinstance(offices, list) or not 1 <= len(offices) <= 2
            or len(set(offices)) != len(offices)
            or any(office not in {"dhaka", "frankfurt"} for office in offices)
        ):
            raise ValueError()
        if (
            type(claims["restricted"]) is not bool
            or not isinstance(claims["tenant"], str) or not claims["tenant"]
        ):
            raise ValueError()
        issued, expires = claims["iat"], claims["exp"]
        now = time.time()
        if (
            type(issued) is not int or type(expires) is not int
            or issued > now + 5 or expires <= now or not 0 < expires - issued <= 60
        ):
            raise ValueError()
        office = claims["office"]
        if office == "GATEWAY":
            if (
                role not in {Role.ADMIN, Role.REVIEWER}
                or set(offices) != {"dhaka", "frankfurt"}
                or (role != Role.ADMIN and not claims["restricted"])
            ):
                raise ValueError()
            # Gateway orchestration uses privileged internal office connections.
            # Its receipts may include restricted rules; do not grant this route
            # to accounts without restricted-source access.
            permissions = {Permission.FEDERATION_ORCHESTRATE, Permission.AUDIT_READ}
        else:
            if office not in {"DHAKA", "FRANKFURT"} or office.lower() not in offices:
                raise ValueError()
            permissions = {Permission.READ_LOCAL, Permission.QUERY_LOCAL}
            if role in {Role.ADMIN, Role.REVIEWER, Role.UPLOADER}:
                permissions.add(Permission.INGEST)
            if role in {Role.ADMIN, Role.REVIEWER}:
                permissions.update({Permission.REVIEW, Permission.AUDIT_READ})
            if claims["restricted"] or role == Role.ADMIN:
                permissions.add(Permission.READ_RESTRICTED)
        return Principal(
            principal_id=f"user:{claims['username']}", tenant_id=claims["tenant"],
            office=office, role=role, permissions=frozenset(permissions),
            display_name=claims["username"],
        )
    except (ValueError, TypeError, KeyError, OSError, UnicodeError) as exc:
        raise AuthenticationError("invalid UI identity") from exc
