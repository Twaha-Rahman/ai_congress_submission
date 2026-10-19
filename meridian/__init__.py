"""Meridian: verifiable institutional memory backend.

Package layout (see README):

    contracts   strict typed I/O models
    storage     sqlite migrations, transactions, repositories
    ingestion   PDF/Slack normalisation, durable jobs
    extraction  provider adapters (live/cached/replay) + evidence validation
    rules       applicability, discrete value sets, finding classification
    temporal    snapshot selection, explicit scoped supersession
    integrity   canonical encoding, Merkle proofs, Ed25519 signatures, bundles
    queries     authorised retrieval and deterministic answers
    security    static demo principals and scope checks
    federation  typed inter-office exchange and egress audit
    office_api  FastAPI application served once per office
    gateway_api FastAPI gateway application
"""

__version__ = "0.1.0"
