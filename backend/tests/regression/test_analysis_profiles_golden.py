"""Golden regression (task 3.4, design.md P5-D4/P5-D5/P5-D6).

Seeds Quintana via the real migration 20261003_0023 (not the seed_quintana()
service helper — this proves the PRODUCTION seed path, byte-for-byte), then
asserts:
  1. resolve_client_catalog()'s product/need-tag id sets exactly equal
     catalog.py's live PRODUCT_CATALOG/NEED_TAGS constants.
  2. The per-call Agent-1 prompt built from that resolved catalog is
     byte-identical to the pre-change module-load DIMENSION["prompt"] value
     for the same (Spanish) language input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ALEMBIC_DIR = BACKEND_DIR / "alembic"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# Captured BEFORE this change via:
#   uv run python -c "from app.analysis.universal.interest.interests import \
#       DIMENSION; import json; print(json.dumps(DIMENSION['prompt']))"
_PRE_CHANGE_PROMPT = "LANGUAGE NOTE: Write the `evidence` field in Spanish. Keep product IDs and need tags as the exact canonical values listed above.\n\nYou are an expert at detecting insurance product interests from sales call transcripts.\n\nA product interest exists when the lead explicitly mentions, asks about, or clearly implies interest in a specific insurance product.\n\nFor each detected interest identify:\n- product: the product ID from the list below (EXACT match required)\n- needs: specific needs the lead expressed for this product — pick from the NEED_TAGS list (at most 3, can be empty)\n- evidence: a direct quote or close paraphrase from the transcript that proves this interest (required — no evidence means no interest)\n- confidence: how certain you are the interest was expressed — low, medium, or high\n\nVALID PRODUCTS (use ONLY these IDs — do not invent new ones):\n  - auto_todo_riesgo\n  - auto_terceros_completo\n  - auto_terceros\n  - moto\n  - hogar\n  - vida\n  - comercio\n  - art\n  - caucion\n\nVALID NEED_TAGS (use ONLY these values — at most 3 per product):\n  - precio_competitivo\n  - mayor_cobertura\n  - menor_franquicia\n  - atencion_personalizada\n  - rapidez\n  - financiacion\n  - comparar_con_actual\n  - renovacion_proxima\n  - COMPARANDO_OPCIONES\n  - other\n\nCONSTRAINTS:\n- Return at most 5 items. If more are detectable, return the 5 with highest confidence.\n- Return an empty items array if no product interest is detected.\n- Every item MUST include transcript evidence.\n- Only use product IDs from the VALID PRODUCTS list — do not create new IDs.\n- Only use need tags from the VALID NEED_TAGS list.\n\nDO NOT include in items:\n- Products the agent mentioned but the lead showed no interest in\n- Vague statements like '¿tienen seguros?' without a specific product\n- Products outside the VALID PRODUCTS list\n- Items where the evidence is a commitment or intent to buy (not an interest signal)\n- Speculation — only include what is clearly expressed in the transcript\n\nReturn JSON with: items (array of product interest objects)."


def _make_migration_alembic_config(db_path: Path):
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


@pytest.fixture
def quintana_migrated_db(tmp_path):
    """Seed quintana-seguros via the real 20261003_0022 -> head migration path
    (not the seed_quintana() service helper) — the production seed path."""
    import sqlite3

    from alembic import command

    db_file = tmp_path / "analysis_profiles_golden.db"
    cfg = _make_migration_alembic_config(db_file)
    command.upgrade(cfg, "20261003_0022")

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO clients (id, name, voice_id, is_active, created_at) "
        "VALUES ('quintana-seguros', 'Quintana Seguros', 'v1', 1, '2026-10-03T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    command.upgrade(cfg, "head")
    return db_file


async def test_quintana_catalog_and_prompt_are_byte_identical_to_pre_change(
    quintana_migrated_db,
):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

    from app.analysis.universal.interest.catalog import NEED_TAGS, PRODUCT_CATALOG
    from app.analysis.universal.interest.interests import _build_prompt
    from app.tenants.revisions_service import resolve_client_catalog

    engine = create_async_engine(f"sqlite+aiosqlite:///{quintana_migrated_db}")
    try:
        async with AsyncSession(engine) as session:
            catalog = await resolve_client_catalog(session, "quintana-seguros")
    finally:
        await engine.dispose()

    assert {p.id for p in catalog.products} == set(PRODUCT_CATALOG)
    assert {n.id for n in catalog.need_tags} == set(NEED_TAGS)
    assert catalog.vertical == "insurance"

    prompt = _build_prompt("Spanish", catalog=catalog)
    assert prompt == _PRE_CHANGE_PROMPT
