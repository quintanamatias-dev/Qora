"""interest/ — 2-phase interest detection pipeline.

Public API
----------
Catalog:
    PRODUCT_CATALOG      list[str]   — 9 authoritative product IDs
    NEED_TAGS            list[str]   — 8 authoritative need tags

Agent 1 (interests):
    InterestItem         Pydantic model — single detected product interest
    InterestsAxis        Pydantic model — up to 5 InterestItems

Agent 2 (interest_level):
    ProductScore         Pydantic model — per-product score entry
    InterestLevelResult  Pydantic model — scored interest level with formula

Pipeline:
    run_interest_pipeline  async function — runs Agent 1 then Agent 2,
                           returns (InterestsAxis|dict, InterestLevelResult|dict)

This package is designed so that:
- ``summarizer.py`` imports only from here (not from sub-modules directly)
- ``catalog.py`` is the single source of truth for valid values
- Future per-client catalogs can be swapped in ``catalog.py`` without
  touching Agent 1, Agent 2, or the orchestrator
"""

from __future__ import annotations

from app.analysis.universal.interest.catalog import NEED_TAGS, PRODUCT_CATALOG
from app.analysis.universal.interest.interest_level import (
    InterestLevelResult,
    ProductScore,
)
from app.analysis.universal.interest.interests import (
    InterestItem,
    InterestsAxis,
    analyze as analyze_interests,
)
from app.analysis.universal.interest.pipeline import run_interest_pipeline

__all__ = [
    # Catalog
    "PRODUCT_CATALOG",
    "NEED_TAGS",
    # Agent 1 models
    "InterestItem",
    "InterestsAxis",
    # Agent 1 analyzer
    "analyze_interests",
    # Agent 2 models
    "ProductScore",
    "InterestLevelResult",
    # Pipeline
    "run_interest_pipeline",
]
