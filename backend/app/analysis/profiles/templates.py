"""Vertical analysis-profile templates (design.md P5-D3).

Two code-only templates: `insurance` (byte-identical to catalog.py's 9
product IDs / 10 need-tag IDs, with labels sourced from
frontend/src/config/dimension-labels.ts's existing entries for those same
IDs) and `generic` (empty — the default for every new client).

A drift-detection test (test_templates.py) asserts the insurance template's
product/need-tag id sets equal catalog.py's live constants exactly — if
catalog.py ever changes, that test fails here first.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.analysis.profiles.schema import AnalysisProfileConfigV1, NeedTagEntry, ProductEntry


class ProfileTemplate(BaseModel):
    vertical: str
    config: AnalysisProfileConfigV1


# ---------------------------------------------------------------------------
# Insurance vertical — authoritative product/need-tag IDs (Issue #51).
#
# These IDs appear verbatim in LLM prompts and in stored CallAnalysis.products/
# specific_needs. Do NOT change IDs without a DB migration for those columns.
#
# catalog.py (app.analysis.universal.interest.catalog) is a thin re-export
# DERIVED FROM this template (Gap B) — this module is now the single source
# of truth, not catalog.py, eliminating the prior duplication-drift risk.
# ---------------------------------------------------------------------------

_PRODUCT_IDS: list[str] = [
    "auto_todo_riesgo",  # Automobile — comprehensive coverage
    "auto_terceros_completo",  # Automobile — third-party + extras
    "auto_terceros",  # Automobile — basic third-party
    "moto",  # Motorcycle
    "hogar",  # Home/property
    "vida",  # Life insurance
    "comercio",  # Commercial / business
    "art",  # Personal accident (ART)
    "caucion",  # Surety bond
]

_NEED_TAG_IDS: list[str] = [
    "precio_competitivo",  # Lead wants a competitive price
    "mayor_cobertura",  # Lead wants broader coverage
    "menor_franquicia",  # Lead wants a lower deductible
    "atencion_personalizada",  # Lead wants personalized service
    "rapidez",  # Lead needs fast turnaround
    "financiacion",  # Lead needs financing / installment options
    "comparar_con_actual",  # Lead wants to compare with their current policy
    "renovacion_proxima",  # Lead's policy is expiring soon
    # post-call-analysis-bi-friendly PR 1: comparison behavior reclassified from
    # pain_points to interests. Use COMPARANDO_OPCIONES for shopping-around signals.
    "COMPARANDO_OPCIONES",  # Lead is actively comparing options / shopping around
    "other",  # Fallback for valid interests that match no specific allowlist tag
]

# Labels sourced from frontend/src/config/dimension-labels.ts (ES/EN pairs for
# the same product/need-tag ids).
_PRODUCT_LABELS: dict[str, tuple[str, str, str | None]] = {
    "auto_todo_riesgo": ("Auto todo riesgo", "Comprehensive auto", None),
    "auto_terceros_completo": ("Auto terceros completo", "Auto third-party complete", None),
    "auto_terceros": ("Auto terceros", "Auto third-party", None),
    "moto": ("Moto", "Motorcycle", None),
    "hogar": ("Hogar", "Home", None),
    "vida": ("Vida", "Life", None),
    "comercio": ("Comercio", "Commercial", None),
    "art": ("ART", "Personal accident (ART)", None),
    "caucion": ("Caución", "Surety bond", None),
}

_NEED_TAG_LABELS: dict[str, tuple[str, str]] = {
    "precio_competitivo": ("Precio competitivo", "Competitive price"),
    "mayor_cobertura": ("Mayor cobertura", "More coverage"),
    "menor_franquicia": ("Menor franquicia", "Lower deductible"),
    "atencion_personalizada": ("Atención personalizada", "Personalized service"),
    "rapidez": ("Rapidez", "Speed"),
    "financiacion": ("Financiación", "Financing"),
    "comparar_con_actual": ("Comparar con actual", "Compare with current"),
    "renovacion_proxima": ("Renovación próxima", "Upcoming renewal"),
    "COMPARANDO_OPCIONES": ("Comparando opciones", "Comparing options"),
    "other": ("Otro", "Other"),
}

insurance = ProfileTemplate(
    vertical="insurance",
    config=AnalysisProfileConfigV1(
        vertical="insurance",
        products=[
            ProductEntry(
                id=product_id,
                label_es=_PRODUCT_LABELS[product_id][0],
                label_en=_PRODUCT_LABELS[product_id][1],
                description=_PRODUCT_LABELS[product_id][2],
            )
            for product_id in _PRODUCT_IDS
        ],
        need_tags=[
            NeedTagEntry(
                id=need_id,
                label_es=_NEED_TAG_LABELS[need_id][0],
                label_en=_NEED_TAG_LABELS[need_id][1],
            )
            for need_id in _NEED_TAG_IDS
        ],
    ),
)

generic = ProfileTemplate(
    vertical="generic",
    config=AnalysisProfileConfigV1(vertical="generic", products=[], need_tags=[]),
)
