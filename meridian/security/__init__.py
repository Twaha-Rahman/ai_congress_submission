"""Static demo identity map and scope enforcement helpers."""

from .auth import (
    AuthenticationError,
    AuthorizationError,
    Permission,
    Principal,
    PrincipalRegistry,
    Role,
)

__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "Permission",
    "Principal",
    "PrincipalRegistry",
    "Role",
]
