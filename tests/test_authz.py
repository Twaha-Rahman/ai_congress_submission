"""Authentication, permissions and restricted-evidence exclusion."""

from __future__ import annotations

import pytest

from meridian.security.auth import (
    AuthenticationError,
    AuthorizationError,
    Permission,
    PrincipalRegistry,
)

from conftest import (
    FIXTURES,
    OfficeHarness,
    T_KNOWN,
    T_VALID,
    loan_target,
)

PRINCIPALS = FIXTURES.parent / "config" / "principals.json"


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> PrincipalRegistry:
    monkeypatch.setenv("DEMO_TOKEN_DHAKA_UPLOADER", "token-uploader")
    monkeypatch.setenv("DEMO_TOKEN_DHAKA_READER", "token-reader")
    monkeypatch.setenv("DEMO_TOKEN_FRANKFURT_READER", "token-frankfurt")
    return PrincipalRegistry.from_file(PRINCIPALS)


def test_bearer_tokens_authenticate_against_the_server_side_map(
    registry: PrincipalRegistry,
) -> None:
    uploader = registry.authenticate("token-uploader")
    assert uploader.principal_id == "dhaka_uploader"
    assert uploader.has(Permission.INGEST)
    assert uploader.has(Permission.READ_RESTRICTED)

    reader = registry.authenticate("token-reader")
    assert reader.principal_id == "dhaka_reader"
    assert not reader.has(Permission.READ_RESTRICTED)
    assert not reader.has(Permission.INGEST)


def test_unknown_or_missing_tokens_are_rejected(registry: PrincipalRegistry) -> None:
    with pytest.raises(AuthenticationError):
        registry.authenticate(None)
    with pytest.raises(AuthenticationError):
        registry.authenticate("not-a-token")


def test_office_tenant_and_restricted_source_access_are_enforced(
    registry: PrincipalRegistry,
) -> None:
    reader = registry.authenticate("token-reader")
    uploader = registry.authenticate("token-uploader")
    frankfurt = registry.authenticate("token-frankfurt")

    assert registry.can_read_source(reader, region="DHAKA", restricted=False)
    assert not registry.can_read_source(reader, region="DHAKA", restricted=True)
    assert registry.can_read_source(uploader, region="DHAKA", restricted=True)
    assert not registry.can_read_source(frankfurt, region="DHAKA", restricted=False)

    with pytest.raises(AuthorizationError):
        registry.require_office(reader, "FRANKFURT")
    with pytest.raises(AuthorizationError):
        registry.require_tenant(reader, "another_tenant")
    with pytest.raises(AuthorizationError):
        registry.require_permission(reader, Permission.READ_RESTRICTED)


def test_restricted_claims_are_excluded_before_computation(
    dhaka_seeded: OfficeHarness,
) -> None:
    # Above USD 1,000,000 both the public v3 policy (2 approvals) and the restricted
    # credit note (3 approvals) apply.  Excluding restricted evidence must change the
    # computed answer, not merely hide a citation.
    amount = 200_000_000
    with_restricted = dhaka_seeded.query(
        loan_target(amount), valid_at=T_VALID, known_at=T_KNOWN, allowed_restricted=True
    )
    without_restricted = dhaka_seeded.query(
        loan_target(amount), valid_at=T_VALID, known_at=T_KNOWN, allowed_restricted=False
    )

    assert "At least 3 approvals" in with_restricted.payload.answer_text
    assert {citation.source_identity for citation in with_restricted.payload.citations} == {
        "dhaka_lending_policy",
        "dhaka_credit_note_restricted",
    }

    assert "At least 2 approvals" in without_restricted.payload.answer_text
    assert {citation.source_identity for citation in without_restricted.payload.citations} == {
        "dhaka_lending_policy"
    }
    assert not any(citation.restricted for citation in without_restricted.payload.citations)
