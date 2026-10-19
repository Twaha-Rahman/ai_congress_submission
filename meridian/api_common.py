"""Shared HTTP plumbing: structured errors, auth dependencies, JSON helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from .contracts.common import ErrorCode
from .security.auth import (
    AuthenticationError,
    AuthorizationError,
    Permission,
    Principal,
    PrincipalRegistry,
)

#: Error code -> HTTP status.  Integrity failures are *not* here: verification
#: problems are reported as structured 200 results, never as generic exceptions.
ERROR_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.UNSUPPORTED_CONTENT: 422,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.EXTRACTION_FAILED: 502,
    ErrorCode.EXTRACTION_NEEDS_REVIEW: 409,
    ErrorCode.CACHE_MISS: 424,
    ErrorCode.REPLAY_FIXTURE_MISSING: 424,
    ErrorCode.MISSING_CREDENTIALS: 412,
    ErrorCode.PROVIDER_ERROR: 502,
    ErrorCode.PROVIDER_TIMEOUT: 504,
    ErrorCode.SCHEMA_VIOLATION: 502,
    ErrorCode.HALLUCINATED_EVIDENCE: 409,
    ErrorCode.MISSING_POLICY: 404,
    ErrorCode.UNSUPPORTED_SEMANTICS: 422,
    ErrorCode.OFFICE_UNAVAILABLE: 503,
    ErrorCode.VERSION_PAYLOAD_MISMATCH: 409,
    ErrorCode.EGRESS_DENIED: 403,
}


class ApiError(Exception):
    """Structured API failure with a stable machine-readable code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code or ERROR_STATUS.get(code, 400)
        self.detail = detail or {}

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={
                "error": {
                    "code": self.code.value,
                    "message": self.message,
                    "detail": self.detail,
                }
            },
        )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(AuthenticationError)
    async def _authn(_request: Request, exc: AuthenticationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": ErrorCode.UNAUTHENTICATED.value, "message": exc.reason}},
        )

    @app.exception_handler(AuthorizationError)
    async def _authz(_request: Request, exc: AuthorizationError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error": {"code": ErrorCode.FORBIDDEN.value, "message": exc.reason}},
        )

    @app.exception_handler(ValidationError)
    async def _validation(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.INVALID_INPUT.value,
                    "message": "request does not match the strict contract schema",
                    "detail": {"errors": exc.errors(include_url=False, include_input=False)},
                }
            },
        )


def bearer_dependency(registry: PrincipalRegistry) -> Callable[[Request], Principal]:
    """FastAPI dependency: authenticate the bearer token, never trust the body."""

    def dependency(request: Request) -> Principal:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("missing bearer token")
        return registry.authenticate(token.strip())

    return dependency


def require(registry: PrincipalRegistry, principal: Principal, permission: Permission) -> None:
    registry.require_permission(principal, permission)


def load_registry(config_dir: Path) -> PrincipalRegistry:
    return PrincipalRegistry.from_file(config_dir / "principals.json")


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    return value


__all__ = [
    "ApiError",
    "ERROR_STATUS",
    "bearer_dependency",
    "install_error_handlers",
    "jsonable",
    "load_registry",
    "require",
]
