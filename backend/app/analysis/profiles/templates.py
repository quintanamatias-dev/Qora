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
from app.analysis.universal.interest.catalog import NEED_TAGS, PRODUCT_CATALOG


class ProfileTemplate(BaseModel):
    vertical: str
    config: AnalysisProfileConfigV1


# Labels sourced from frontend/src/config/dimension-labels.ts (ES/EN pairs for
# the same PRODUCT_CATALOG / NEED_TAGS ids).
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
            for product_id in PRODUCT_CATALOG
        ],
        need_tags=[
            NeedTagEntry(
                id=need_id,
                label_es=_NEED_TAG_LABELS[need_id][0],
                label_en=_NEED_TAG_LABELS[need_id][1],
            )
            for need_id in NEED_TAGS
        ],
    ),
)

generic = ProfileTemplate(
    vertical="generic",
    config=AnalysisProfileConfigV1(vertical="generic", products=[], need_tags=[]),
)
