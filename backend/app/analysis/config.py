"""ExtractionConfig + AxisFieldDef — per-client extraction configuration.

Stored as JSON in ``Client.extraction_config`` and validated here before being
fed into the dynamic model builder and prompt builder. Only OpenAI-safe scalar
types are permitted for ``extra_axes`` to keep JSON Schema compatibility with
the Structured Outputs API.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

# Universal axis names — used for ``disabled_axes`` membership check.
_BASE_AXIS_NAMES: frozenset[str] = frozenset(
    {
        "service_issues",
        "profile_facts",
        "commitment_signals",
        "abandonment_reason",
    }
)

# All top-level PostCallAnalysis field names, used to detect ``extra_axes``
# name collisions with the composite root schema.
_BASE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "summary",
        "objections",
        "interest_level",
        "next_action_suggested",
        "misc_notes",
        "data_corrections",
        "call_outcome",
        "detected_interests",
        "identified_problem",
        "service_issues",
        "profile_facts",
        "commitment_signals",
        "abandonment_reason",
    }
)

_KNOWN_BASE_AXES: frozenset[str] = _BASE_AXIS_NAMES

_AXIS_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

_ALLOWED_FIELD_TYPES: frozenset[str] = frozenset({"str", "list[str]", "int"})


class AxisFieldDef(BaseModel):
    """Definition of a single client-specific extra axis field."""

    name: str = Field(description="Field name — snake_case, ^[a-z][a-z0-9_]{1,30}$")
    field_type: Literal["str", "list[str]", "int"] = Field(
        description="Python type for this axis field — one of: str, list[str], int"
    )
    description: str = Field(
        description="Human-readable description passed to Field(description=...)"
    )

    @field_validator("name")
    @classmethod
    def name_must_be_snake_case(cls, v: str) -> str:
        if not _AXIS_NAME_RE.match(v):
            raise ValueError(
                f"AxisFieldDef.name must match ^[a-z][a-z0-9_]{{1,30}}$, got: {v!r}"
            )
        return v


class ExtractionConfig(BaseModel):
    """Per-client extraction configuration stored as JSON in Client.extraction_config.

    - disabled_axes: base axes to skip (must be in _KNOWN_BASE_AXES)
    - extra_axes: client-specific additional fields (max 10, no name collision)
      Accepts EITHER list[AxisFieldDef] (native) OR dict[str, str] (legacy shape,
      auto-converted to list[AxisFieldDef] with generated descriptions).
    - prompt_addendum: text appended after axis instructions in the system prompt
    """

    disabled_axes: list[str] = Field(
        default_factory=list,
        description="Base axis names to skip (subset of known base axes)",
    )
    extra_axes: list[AxisFieldDef] = Field(
        default_factory=list,
        description="Client-specific additional axes (max 10)",
    )
    prompt_addendum: str = Field(
        default="",
        description="Appended after axis instructions in the generated system prompt",
        validation_alias=AliasChoices("prompt_addendum", "context_description"),
    )

    @field_validator("extra_axes", mode="before")
    @classmethod
    def coerce_dict_extra_axes(cls, v: object) -> object:
        """Accept legacy dict[str, str] shape and convert to list[AxisFieldDef] dicts.

        Forward-compat shim: old spec used ``{"field_name": "field_type"}`` but
        the implementation uses ``list[AxisFieldDef]``. Both shapes are
        supported so JSON payloads serialised against either spec version are
        accepted.
        """
        if isinstance(v, dict):
            return [
                {
                    "name": name,
                    "field_type": field_type,
                    "description": f"{name} (auto-generated)",
                }
                for name, field_type in v.items()
            ]
        return v  # type: ignore[return-value]

    @property
    def context_description(self) -> str:
        """Alias for prompt_addendum — forward-compat with spec field name."""
        return self.prompt_addendum

    @field_validator("disabled_axes")
    @classmethod
    def disabled_axes_must_be_known(cls, v: list[str]) -> list[str]:
        unknown = set(v) - _KNOWN_BASE_AXES
        if unknown:
            raise ValueError(
                f"disabled_axes references unknown axis names: {sorted(unknown)}. "
                f"Known axes: {sorted(_KNOWN_BASE_AXES)}"
            )
        return v

    @model_validator(mode="after")
    def validate_extra_axes(self) -> "ExtractionConfig":
        if len(self.extra_axes) > 10:
            raise ValueError(
                f"extra_axes may not have more than 10 entries, got {len(self.extra_axes)}"
            )
        for ax in self.extra_axes:
            if ax.name in _BASE_FIELD_NAMES:
                raise ValueError(
                    f"extra_axes name {ax.name!r} collides with a base PostCallAnalysis field. "
                    "Choose a different name."
                )
        return self
