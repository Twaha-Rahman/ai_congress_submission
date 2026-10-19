"""Merkle tree over committed clause leaves, following RFC 9162 section 2.1.

The root and all interior hashes use domain separated SHA-256:

    leaf_hash = SHA256(0x00 || canonical_leaf_payload)
    node_hash = SHA256(0x01 || left_child_hash || right_child_hash)

The tree follows the recursive *largest power of two* split of RFC 9162 rather than
an invented odd-leaf convention.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .canonical import leaf_hash, node_hash

MAX_TREE_SIZE = 1_000_000


def largest_power_of_two_below(n: int) -> int:
    if n < 2:
        raise ValueError("largest_power_of_two_below requires n >= 2")
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def merkle_root_hash(leaf_hashes: Sequence[bytes]) -> bytes:
    """MTH of RFC 9162 section 2.1.1."""

    n = len(leaf_hashes)
    if n == 0:
        raise ValueError("empty Merkle tree is not defined")
    if n == 1:
        return leaf_hashes[0]
    k = largest_power_of_two_below(n)
    return node_hash(merkle_root_hash(leaf_hashes[:k]), merkle_root_hash(leaf_hashes[k:]))


def merkle_root_hex(leaf_hashes: Sequence[bytes]) -> str:
    return merkle_root_hash(leaf_hashes).hex()


def inclusion_path(leaf_hashes: Sequence[bytes], index: int) -> list[bytes]:
    """PATH(m, D[n]) of RFC 9162 section 2.1.3.1."""

    n = len(leaf_hashes)
    if not 0 <= index < n:
        raise IndexError("leaf index out of range")
    if n == 1:
        return []
    k = largest_power_of_two_below(n)
    if index < k:
        return inclusion_path(leaf_hashes[:k], index) + [merkle_root_hash(leaf_hashes[k:])]
    return inclusion_path(leaf_hashes[k:], index - k) + [merkle_root_hash(leaf_hashes[:k])]


def verify_inclusion(
    *,
    leaf_hash_value: bytes,
    index: int,
    tree_size: int,
    siblings: Sequence[bytes],
    root: bytes,
) -> bool:
    """RFC 9162 section 2.1.3.2 inclusion proof verification."""

    if tree_size < 1 or tree_size > MAX_TREE_SIZE:
        return False
    if index < 0 or index >= tree_size:
        return False
    if len(siblings) > 64:
        return False
    fn = index
    sn = tree_size - 1
    r = leaf_hash_value
    for p in siblings:
        if len(p) != 32:
            return False
        if sn == 0:
            return False
        if (fn & 1) or fn == sn:
            r = node_hash(p, r)
            while not (fn & 1) and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    if sn != 0:
        return False
    return r == root


def build_tree(leaf_payloads: Iterable[bytes]) -> tuple[list[bytes], bytes]:
    """Return ``(leaf_hashes, root)`` for the given canonical leaf payloads."""

    hashes = [leaf_hash(payload) for payload in leaf_payloads]
    if not hashes:
        raise ValueError("cannot build a Merkle tree with no leaves")
    return hashes, merkle_root_hash(hashes)
