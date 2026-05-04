"""Interest pipeline catalog — authoritative product and need tag lists.

These are the only valid values Agent 1 (interests.py) may return.
Agent 1's prompt is generated from these lists so the LLM stays constrained.

Future migration path:
    - PRODUCT_CATALOG and NEED_TAGS are plain ``list[str]`` today (simple, testable).
    - When per-client configuration is required, replace each with a lookup
      function or registry that reads from DB / client config:
          ``get_product_catalog(client_id: str) -> list[str]``
          ``get_need_tags(client_id: str) -> list[str]``
    - Agent 1 and Agent 2 only import from this module, so the change is isolated
      to this file — no downstream callers need updating.

Source: Issue #51 (authoritative).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Product IDs — 9 insurance products offered by Quintana Seguros.
#
# These IDs appear verbatim in LLM prompts and in stored ``detected_interests``.
# Do NOT change IDs without a DB migration for ``CallAnalysis.products``.
# ---------------------------------------------------------------------------

PRODUCT_CATALOG: list[str] = [
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

# ---------------------------------------------------------------------------
# Need tags — 8 lead needs the agent may detect during a call.
#
# Stored as elements of ``InterestItem.needs`` (max 3 per item).
# ---------------------------------------------------------------------------

NEED_TAGS: list[str] = [
    "precio_competitivo",  # Lead wants a competitive price
    "mayor_cobertura",  # Lead wants broader coverage
    "menor_franquicia",  # Lead wants a lower deductible
    "atencion_personalizada",  # Lead wants personalized service
    "rapidez",  # Lead needs fast turnaround
    "financiacion",  # Lead needs financing / installment options
    "comparar_con_actual",  # Lead wants to compare with their current policy
    "renovacion_proxima",  # Lead's policy is expiring soon
]
