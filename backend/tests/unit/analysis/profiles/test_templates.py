"""Phase 1 (analysis-profiles) — Task 1.2: insurance/generic ProfileTemplate constants."""

from __future__ import annotations


def test_insurance_template_matches_catalog_ids_exactly():
    from app.analysis.profiles.templates import insurance
    from app.analysis.universal.interest.catalog import NEED_TAGS, PRODUCT_CATALOG

    product_ids = {p.id for p in insurance.config.products}
    need_tag_ids = {n.id for n in insurance.config.need_tags}

    assert product_ids == set(PRODUCT_CATALOG)
    assert need_tag_ids == set(NEED_TAGS)
    assert insurance.vertical == "insurance"
    assert insurance.config.vertical == "insurance"


def test_generic_template_is_empty():
    from app.analysis.profiles.templates import generic

    assert generic.config.products == []
    assert generic.config.need_tags == []
    assert generic.vertical == "generic"
    assert generic.config.vertical == "generic"
