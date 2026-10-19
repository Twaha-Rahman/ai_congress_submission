"""Model extraction: provider adapters, modes, caching and evidence validation."""

from .cache import CachedExtractionProvider, compute_cache_key
from .openrouter import OpenRouterExtractionProvider, strict_json_schema
from .provider import (
    ClauseInput,
    ExtractionProvider,
    ExtractionRequest,
    ProviderPrerequisiteError,
    ProviderResult,
)
from .replay import ReplayExtractionProvider
from .service import ModelStageService
from .validate import (
    Rejection,
    ReviewItem,
    ValidationOutcome,
    ValidatorClause,
    VerifiedRule,
    rule_summary,
    validate_proposal,
)

__all__ = [
    "CachedExtractionProvider",
    "ClauseInput",
    "ExtractionProvider",
    "ExtractionRequest",
    "ModelStageService",
    "OpenRouterExtractionProvider",
    "ProviderPrerequisiteError",
    "ProviderResult",
    "Rejection",
    "ReplayExtractionProvider",
    "ReviewItem",
    "ValidationOutcome",
    "ValidatorClause",
    "VerifiedRule",
    "compute_cache_key",
    "rule_summary",
    "strict_json_schema",
    "validate_proposal",
]
