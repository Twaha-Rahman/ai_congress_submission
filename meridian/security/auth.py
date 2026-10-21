"""Server-side account/service identity authentication and scope enforcement.

Internal service tokens live in environment variables. Browser accounts arrive as
short-lived signed identities from the authenticated UI server. Authorisation is evaluated before any retrieval or
model call, and object access is scoped by server-derived tenant/office, never by a
client-supplied identifier.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Role(str, Enum):
    ADMIN = "admin"
    UPLOADER = "uploader"
    REVIEWER = "reviewer"
    READER = "reader"
    OFFICE_SERVICE = "office_service"
    GATEWAY_SERVICE = "gateway_service"


class Permission(str, Enum):
    INGEST = "ingest"
    READ_LOCAL = "read_local"
    QUERY_LOCAL = "query_local"
    READ_RESTRICTED = "read_restricted"
    REVIEW = "review"
    FEDERATION_SERVE = "federation_serve"
    FEDERATION_ORCHESTRATE = "federation_orchestrate"
    AUDIT_READ = "audit_read"
    INTERNAL_EGRESS_READ = "internal_egress_read"


@dataclass(frozen=True)
class Principal:
    principal_id: str
    tenant_id: str
    office: str
    role: Role
    permissions: frozenset[Permission]
    display_name: str

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def public_dict(self) -> dict[str, str]:
        return {
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "office": self.office,
            "role": self.role.value,
        }


class AuthenticationError(PermissionError):
    def __init__(self, reason: str, *, status_code: int = 401) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class AuthorizationError(PermissionError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PrincipalRegistry:
    """Authenticate delegated UI accounts and the internal static identity map."""

    def __init__(self, principals: list[dict], *, offline_token: str | None = None) -> None:
        self._principals = principals
        self._offline_token = offline_token

    @classmethod
    def from_file(cls, path: str | Path, *, offline_token: str | None = None) -> "PrincipalRegistry":
        data = json.loads(Path(path).read_text("utf-8"))
        return cls(data["principals"], offline_token=offline_token)

    @classmethod
    def from_env(cls, path: str | Path) -> "PrincipalRegistry":
        return cls.from_file(path)

    def token_for(self, principal_id: str) -> str | None:
        for item in self._principals:
            if item["principal_id"] == principal_id:
                value = os.environ.get(item["token_env"], "")
                return value or None
        return None

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise AuthenticationError("missing bearer token")
        if token.startswith("ui1."):
            from meridian.security.ui_identity import authenticate_ui_token

            return authenticate_ui_token(token)
        for item in self._principals:
            expected = os.environ.get(item["token_env"], "")
            if not expected:
                continue
            if hmac.compare_digest(expected, token):
                return Principal(
                    principal_id=item["principal_id"],
                    tenant_id=item["tenant_id"],
                    office=item["office"],
                    role=Role(item["role"]),
                    permissions=frozenset(Permission(value) for value in item["permissions"]),
                    display_name=item.get("display_name", item["principal_id"]),
                )
        raise AuthenticationError("unknown bearer token")

    def configured_principal_ids(self) -> list[str]:
        return [
            item["principal_id"]
            for item in self._principals
            if os.environ.get(item["token_env"], "")
        ]

    def require_permission(self, principal: Principal, permission: Permission) -> None:
        if not principal.has(permission):
            raise AuthorizationError(
                f"principal {principal.principal_id!r} lacks permission {permission.value!r}"
            )

    def require_office(self, principal: Principal, region: str) -> None:
        if principal.office.upper() != region.upper():
            raise AuthorizationError(
                f"principal {principal.principal_id!r} is scoped to {principal.office}, not {region}"
            )

    def require_tenant(self, principal: Principal, tenant_id: str) -> None:
        if principal.tenant_id != tenant_id:
            raise AuthorizationError(
                f"principal {principal.principal_id!r} belongs to a different tenant"
            )

    def can_read_source(self, principal: Principal, *, region: str, restricted: bool) -> bool:
        if principal.office.upper() != region.upper():
            return False
        if not principal.has(Permission.READ_LOCAL):
            return False
        if restricted and not principal.has(Permission.READ_RESTRICTED):
            return False
        return True
