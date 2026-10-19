"""Canonical encoding, Merkle commitments, signatures and bundle verification."""

from .bundles import (
    BundleClause,
    SignedManifestPayload,
    build_clause_proof,
    claim_hash,
    clause_leaf_payload,
    verify_bundle,
    verify_clause_proof,
)
from .canonical import (
    CanonicalEncodingError,
    canonical_hash_hex,
    canonical_json_bytes,
    leaf_hash,
    leaf_hash_hex,
    node_hash,
    sha256_hex,
    to_canonical_value,
)
from .merkle import (
    build_tree,
    inclusion_path,
    largest_power_of_two_below,
    merkle_root_hex,
    verify_inclusion,
)
from .signing import (
    PinnedKeyRegistry,
    SignatureError,
    Signer,
    TrustedKey,
    verify_signature,
    verify_with_registry,
)

__all__ = [
    "BundleClause",
    "CanonicalEncodingError",
    "PinnedKeyRegistry",
    "SignatureError",
    "SignedManifestPayload",
    "Signer",
    "TrustedKey",
    "build_clause_proof",
    "build_tree",
    "canonical_hash_hex",
    "canonical_json_bytes",
    "claim_hash",
    "clause_leaf_payload",
    "inclusion_path",
    "largest_power_of_two_below",
    "leaf_hash",
    "leaf_hash_hex",
    "merkle_root_hex",
    "node_hash",
    "sha256_hex",
    "to_canonical_value",
    "verify_bundle",
    "verify_clause_proof",
    "verify_inclusion",
    "verify_signature",
    "verify_with_registry",
]
