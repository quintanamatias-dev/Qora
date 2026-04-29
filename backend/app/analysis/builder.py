"""Dynamic Pydantic model builder for per-client extraction configs.

Composes a model from PostCallAnalysis fields minus disabled axes plus an
``extra_axes_data`` JSON catch-all when the client defines extra fields. Output
is compatible with OpenAI ``parse(response_format=...)``.
"""

from __future__ import annotations

import json as _json
from collections import OrderedDict

from pydantic import BaseModel, Field as PydanticField, create_model

from app.analysis.config import ExtractionConfig
from app.analysis.schema import PostCallAnalysis

# extra_axes field_type → Python annotation for create_model().
_FIELD_TYPE_MAP: dict[str, type] = {
    "str": str,
    "list[str]": list,
    "int": int,
}


def _config_cache_key(config: ExtractionConfig) -> str:
    """Stable string key for caching based on config content."""
    return _json.dumps(
        {
            "disabled_axes": sorted(config.disabled_axes),
            "extra_axes": [
                {
                    "name": ax.name,
                    "field_type": ax.field_type,
                    "description": ax.description,
                }
                for ax in sorted(config.extra_axes, key=lambda x: x.name)
            ],
            "prompt_addendum": config.prompt_addendum,
        },
        sort_keys=True,
    )


def _make_model_for_config(config: "ExtractionConfig") -> type[BaseModel]:
    """Build the Pydantic model for the given ExtractionConfig."""
    disabled = set(config.disabled_axes)

    base_fields: dict[str, tuple] = {}
    for field_name, field_info in PostCallAnalysis.model_fields.items():
        if field_name in disabled:
            continue
        # field_info.annotation is the resolved type — using __annotations__
        # directly returns string names that fail to resolve when this builder
        # lives in a different module than the universal axis classes.
        base_fields[field_name] = (field_info.annotation, field_info)

    if config.extra_axes:
        base_fields["extra_axes_data"] = (
            dict | None,
            PydanticField(
                default=None,
                description="Client-specific extra axis data (JSON catch-all for extensions)",
            ),
        )

    DynamicModel = create_model(
        "DynamicPostCallAnalysis",
        __base__=None,
        **base_fields,
    )
    return DynamicModel


_MODEL_CACHE_MAX_SIZE: int = 100

# LRU model cache keyed by stable JSON config repr; evicts oldest at capacity.
_model_cache: "OrderedDict[str, type[BaseModel]]" = OrderedDict()


def build_analysis_model(config: "ExtractionConfig | None") -> type[BaseModel]:
    """Return a Pydantic model class composed from PostCallAnalysis + config extensions.

    NULL config → returns PostCallAnalysis unchanged (backward compat).
    Compatible with OpenAI parse(response_format=...).
    """
    if config is None:
        return PostCallAnalysis

    cache_key = _config_cache_key(config)

    if cache_key in _model_cache:
        _model_cache.move_to_end(cache_key)
        return _model_cache[cache_key]

    model = _make_model_for_config(config)

    if len(_model_cache) >= _MODEL_CACHE_MAX_SIZE:
        _model_cache.popitem(last=False)

    _model_cache[cache_key] = model
    return model
