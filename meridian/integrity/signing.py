"""Ed25519 signing and pinned-key verification.

Private keys are generated locally and never committed.  Verification always uses a
pinned public key from the trusted registry; a public key supplied by the same
untrusted response is never accepted.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class SignatureError(ValueError):
    """Signature or key material could not be used."""


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    region: str
    public_key_hex: str


class PinnedKeyRegistry:
    """Registry of trusted public keys, loaded from local configuration."""

    def __init__(self, keys: Iterable[TrustedKey]) -> None:
        self._keys = {key.key_id: key for key in keys}

    @classmethod
    def from_json_file(cls, path: str | Path) -> "PinnedKeyRegistry":
        data = json.loads(Path(path).read_text("utf-8"))
        keys = [
            TrustedKey(
                key_id=item["key_id"],
                region=item["region"],
                public_key_hex=item["public_key_hex"],
            )
            for item in data.get("keys", [])
        ]
        return cls(keys)

    def write_json_file(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1",
            "keys": [
                {
                    "key_id": key.key_id,
                    "region": key.region,
                    "public_key_hex": key.public_key_hex,
                }
                for key in sorted(self._keys.values(), key=lambda k: k.key_id)
            ],
        }
        Path(path).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def get(self, key_id: str) -> TrustedKey | None:
        return self._keys.get(key_id)

    def require(self, key_id: str) -> TrustedKey:
        key = self._keys.get(key_id)
        if key is None:
            raise SignatureError(f"key id {key_id!r} is not pinned in the verifier registry")
        return key

    def key_ids(self) -> list[str]:
        return sorted(self._keys)


class Signer:
    """Ed25519 signer for one office."""

    def __init__(self, key_id: str, region: str, private_key: Ed25519PrivateKey) -> None:
        self.key_id = key_id
        self.region = region
        self._private_key = private_key

    @classmethod
    def generate(cls, *, key_id: str, region: str) -> "Signer":
        return cls(key_id, region, Ed25519PrivateKey.generate())

    @classmethod
    def load_or_create(cls, *, key_id: str, region: str, key_dir: str | Path) -> "Signer":
        directory = Path(key_dir)
        directory.mkdir(parents=True, exist_ok=True)
        private_path = directory / f"{key_id}.ed25519.key"
        if private_path.exists():
            raw = private_path.read_bytes()
            private_key = Ed25519PrivateKey.from_private_bytes(raw)
            _restrict_permissions(private_path)
            return cls(key_id, region, private_key)
        signer = cls.generate(key_id=key_id, region=region)
        raw = signer._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_path.write_bytes(raw)
        _restrict_permissions(private_path)
        return signer

    @property
    def public_key_hex(self) -> str:
        return (
            self._private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            .hex()
        )

    def trusted_key(self) -> TrustedKey:
        return TrustedKey(self.key_id, self.region, self.public_key_hex)

    def sign(self, payload: bytes) -> str:
        return base64.b64encode(self._private_key.sign(payload)).decode("ascii")

    def sign_and_hash(self, payload: bytes) -> tuple[str, str]:
        return self.sign(payload), __import__("hashlib").sha256(payload).hexdigest()


def _restrict_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass


def verify_signature(payload: bytes, signature_b64: str, public_key_hex: str) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception:
        return False
    try:
        public_key.verify(signature, payload)
    except InvalidSignature:
        return False
    return True


def verify_with_registry(
    payload: bytes, signature_b64: str, key_id: str, registry: PinnedKeyRegistry
) -> tuple[bool, str | None]:
    """Return ``(verified, reason)``; missing pins are failures, not skips."""

    key = registry.get(key_id)
    if key is None:
        return False, f"key_id {key_id!r} is not pinned"
    if not verify_signature(payload, signature_b64, key.public_key_hex):
        return False, f"signature does not verify against pinned key {key_id!r}"
    return True, None
