"""Analysis profile config schema (design.md P5-D2, Interfaces/Contracts).

AnalysisProfileConfigV1 is the validated shape stored as JSON inside every
client_analysis_profile_revisions.config row — a FULL snapshot (products +
need_tags), not a sparse override set, mirroring AgentConfigV1's revision
pattern rather than ClientConfigV1's sparse one (the analysis profile has no
"inherit from elsewhere" concept to be sparse against).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class ProductEntry(BaseModel):
    id: str
    label_es: str
    label_en: str
    description: str | None = None

    @field_validator("label_es", "label_en")
    @classmethod
    def _non_empty_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be empty")
        return value


class NeedTagEntry(BaseModel):
    id: str
    label_es: str
    label_en: str

    @field_validator("label_es", "label_en")
    @classmethod
    def _non_empty_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be empty")
        return value


class AnalysisProfileConfigV1(BaseModel):
    schema_version: Literal[1] = 1
    vertical: str
    products: list[ProductEntry] = []
    need_tags: list[NeedTagEntry] = []
