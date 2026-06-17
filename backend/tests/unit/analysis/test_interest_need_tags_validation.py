"""Behavioral contract tests for NEED_TAGS enforcement on InterestItem.needs.

Acceptance criteria from spec: call-analysis-dimensions
- "Interests Emit from NEED_TAGS Allowlist Only"
- "Near-duplicate tags rejected" → free-form strings must NOT survive
- "Unknown interest falls back to `other`"

Blocker (fresh review): InterestItem(needs=['buscando alternativas']) used to
validate successfully, letting arbitrary near-duplicate free-form tags survive.
The fix normalizes any need tag NOT in NEED_TAGS to 'other' at model validation,
preserving BI-friendly controlled output (no crash, no arbitrary tags stored).

These are behavioral contract tests on the schema/post-processing OUTCOME — they
do not assert prompt substrings.

Tasks 1.5 → 1.6 (PR 1)
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Invalid free-form need tags MUST NOT survive — normalized to 'other'
# ---------------------------------------------------------------------------


def test_invalid_freeform_need_tag_normalized_to_other():
    """The exact review-cited near-duplicate 'buscando alternativas' must NOT survive.

    Spec: arbitrary near-duplicate free-form tags must be suppressed. The valid
    output for an unknown interest signal is the 'other' fallback tag.
    """
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="auto_todo_riesgo",
        needs=["buscando alternativas"],
        evidence="estoy buscando alternativas",
        confidence="high",
    )

    assert "buscando alternativas" not in item.needs, (
        "Free-form near-duplicate tag 'buscando alternativas' MUST NOT survive validation"
    )
    assert item.needs == ["other"], (
        f"Unknown need tag must normalize to ['other'], got {item.needs!r}"
    )


def test_valid_need_tag_preserved_unchanged():
    """A valid allowlist tag passes through untouched (triangulation — different path)."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="auto_todo_riesgo",
        needs=["precio_competitivo"],
        evidence="quiero un precio más bajo",
        confidence="high",
    )

    assert item.needs == ["precio_competitivo"], (
        f"Valid allowlist tag must be preserved, got {item.needs!r}"
    )


def test_comparando_opciones_tag_preserved():
    """COMPARANDO_OPCIONES (comparison signal) is a valid allowlist tag and survives."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="auto_todo_riesgo",
        needs=["COMPARANDO_OPCIONES"],
        evidence="estoy comparando con varias aseguradoras",
        confidence="medium",
    )

    assert item.needs == ["COMPARANDO_OPCIONES"]


def test_mixed_valid_and_invalid_tags_normalizes_only_invalid():
    """Mixed list: valid tags survive, invalid ones become 'other' (no duplicates kept)."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="hogar",
        needs=["mayor_cobertura", "buscando otra cosa"],
        evidence="quiero más cobertura y estoy viendo opciones",
        confidence="medium",
    )

    assert "buscando otra cosa" not in item.needs, (
        "Invalid free-form tag must not survive"
    )
    assert "mayor_cobertura" in item.needs, "Valid tag must be preserved"
    assert "other" in item.needs, "Invalid tag must be normalized to 'other'"


def test_duplicate_invalid_tags_collapse_to_single_other():
    """Two distinct invalid tags collapse to a single 'other' (no arbitrary duplicates)."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="auto_terceros",
        needs=["buscando alternativas", "viendo precios"],
        evidence="estoy viendo qué hay en el mercado",
        confidence="low",
    )

    assert item.needs.count("other") == 1, (
        f"Multiple invalid tags must collapse to a single 'other', got {item.needs!r}"
    )
    assert all(tag == "other" for tag in item.needs)


def test_every_emitted_need_tag_is_in_allowlist():
    """Contract: after validation, EVERY emitted need tag is in NEED_TAGS.

    This is the BI-friendly controlled-output guarantee — no tag outside the
    catalog can be stored, regardless of what the LLM returns.
    """
    from app.analysis.universal.interest.catalog import NEED_TAGS
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="moto",
        needs=["renovacion_proxima", "algo inventado por el modelo"],
        evidence="se me vence pronto y estoy mirando",
        confidence="high",
    )

    for tag in item.needs:
        assert tag in NEED_TAGS, (
            f"Emitted need tag {tag!r} is NOT in the NEED_TAGS allowlist"
        )


def test_empty_needs_stays_empty():
    """Empty needs list is valid and untouched by normalization."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="vida",
        needs=[],
        evidence="me interesa un seguro de vida",
        confidence="medium",
    )

    assert item.needs == []
