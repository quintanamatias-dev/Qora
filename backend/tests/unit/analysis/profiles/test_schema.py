"""Phase 1 (analysis-profiles) — Task 1.1: AnalysisProfileConfigV1 schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_product_entry_rejects_empty_label():
    from app.analysis.profiles.schema import ProductEntry

    with pytest.raises(ValidationError):
        ProductEntry(id="hogar", label_es="", label_en="Home")


def test_need_tag_entry_rejects_empty_label():
    from app.analysis.profiles.schema import NeedTagEntry

    with pytest.raises(ValidationError):
        NeedTagEntry(id="rapidez", label_es="Rapidez", label_en="")


def test_analysis_profile_config_defaults_to_empty_lists():
    from app.analysis.profiles.schema import AnalysisProfileConfigV1

    config = AnalysisProfileConfigV1(vertical="generic")
    assert config.products == []
    assert config.need_tags == []
    assert config.schema_version == 1
