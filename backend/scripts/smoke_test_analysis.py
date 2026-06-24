"""Smoke test for the 13-dimension Universal Analysis pipeline.

Sends two crafted transcripts through _call_gpt_summarize() and validates
that each dimension fires correctly. Also captures every GPT prompt/response
for manual review.

Usage:
    cd backend && python scripts/smoke_test_analysis.py

Requires:
    - OPENAI_API_KEY in environment (or .env file)
    - No DB required — bypasses persistence entirely
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Add backend to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env before importing app modules
from dotenv import load_dotenv

# B8: Load from repo-root/.env (single source of truth).
# Path resolution: __file__ (backend/scripts/smoke_test_analysis.py)
#   → .parent = backend/scripts/ → .parent = backend/ → .parent = repo-root/
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# GPT Call Interceptor — captures every prompt sent to OpenAI
# ---------------------------------------------------------------------------

_captured_calls: list[dict[str, Any]] = []


def _make_interceptor(original_parse, original_create):
    """Create wrapper functions that log every OpenAI call."""

    async def intercepted_parse(**kwargs):
        call_record = {
            "method": "beta.chat.completions.parse",
            "model": kwargs.get("model"),
            "messages": kwargs.get("messages"),
            "response_format": (
                kwargs.get("response_format").__name__
                if hasattr(kwargs.get("response_format"), "__name__")
                else str(kwargs.get("response_format"))
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        start = time.time()
        result = await original_parse(**kwargs)
        call_record["duration_ms"] = round((time.time() - start) * 1000)
        call_record["response_preview"] = str(result.choices[0].message.parsed)[:500]
        _captured_calls.append(call_record)
        return result

    async def intercepted_create(**kwargs):
        call_record = {
            "method": "chat.completions.create",
            "model": kwargs.get("model"),
            "messages": kwargs.get("messages"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        start = time.time()
        result = await original_create(**kwargs)
        call_record["duration_ms"] = round((time.time() - start) * 1000)
        call_record["response_preview"] = (result.choices[0].message.content or "")[
            :500
        ]
        _captured_calls.append(call_record)
        return result

    return intercepted_parse, intercepted_create


# ---------------------------------------------------------------------------
# Transcript 1: POSITIVE — Complete call, high interest, all dimensions active
# ---------------------------------------------------------------------------

TRANSCRIPT_POSITIVE = """\
Agente: Hola, buenas tardes. Habla Jaumpablo de Quintana Seguros. ¿Hablo con Martín Rodríguez?
Lead: Sí, sí, hola. ¿Qué tal?
Agente: ¿Cómo estás, Martín? Te llamaba porque vimos que habías consultado por un seguro de auto. ¿Tenés un minutito?
Lead: Sí, dale. Justamente estoy necesitando porque se me vence el seguro el mes que viene y me aumentaron un cuarenta por ciento. Es una locura lo que me están cobrando.
Agente: Te entiendo perfectamente. Es una queja muy común últimamente. ¿Con qué compañía estás actualmente?
Lead: Estoy con La Caja. Mirá, no me quejo del servicio en general, pero cuando tuve un siniestro el año pasado tardaron tres meses en resolver el reclamo. Tres meses sin respuesta. Llamaba y nadie me atendía. Un desastre.
Agente: Uy, lamento escuchar eso. Nosotros tenemos un compromiso de resolución de siniestros en 72 horas hábiles. ¿Qué auto tenés?
Lead: Tengo un Toyota Corolla 2022. Ah no, perdón, en realidad es un 2023. Me confundí. El modelo es un Corolla Cross, no Corolla a secas.
Agente: Perfecto, Toyota Corolla Cross 2023. ¿Querés un seguro todo riesgo o terceros completo?
Lead: Mirá, la verdad que me interesa todo riesgo para el auto, y también quería consultar por un seguro de hogar. Tenemos un departamento y no tenemos nada. Mi esposa me viene diciendo hace meses que tenemos que asegurar los contenidos.
Agente: Excelente. El auto todo riesgo y hogar. ¿Tienen algún requisito particular? ¿Buscan algo con franquicia baja, buen precio...?
Lead: Principalmente precio competitivo pero con buena cobertura. Con La Caja pagaba mucho por poca cobertura. Y si puede ser con menor franquicia, mejor.
Agente: Perfecto. Mirá, te armo una cotización para ambos. El todo riesgo del Corolla Cross 2023 y el seguro de hogar con cobertura de contenidos.
Lead: Dale, genial. ¿Me la podés mandar mañana? Porque hoy estoy medio complicado, trabajo en la municipalidad y tengo reuniones hasta las seis.
Agente: Sin problema, mañana a primera hora te la mando por WhatsApp. ¿Este es tu número de WhatsApp?
Lead: Sí, este mismo. Ah, y mi mail es martinrodriguez@gmail.com por si necesitás mandarme algo por escrito. Yo soy de consultar las cosas con mi señora antes de decidir, así que si me mandás algo detallado mejor.
Agente: Perfecto Martín, te mando todo detallado mañana. ¿Algo más que quieras consultar?
Lead: No, por ahora está bien. Ah sí, una cosa: ¿es muy caro? Porque mi cuñado me dijo que los seguros todo riesgo están carísimos este año.
Agente: Mirá, depende mucho del auto y la zona, pero te hago el mejor precio posible. Somos bastante competitivos en Corolla Cross. Mañana cuando veas la cotización me decís qué te parece.
Lead: Dale, perfecto. Muchas gracias Jaumpablo.
Agente: Gracias a vos Martín, te mando todo mañana. ¡Que tengas buena tarde!
Lead: Igualmente, chau."""

EXPECTED_POSITIVE = {
    "summary": {
        "check": lambda s: isinstance(s, str) and len(s) > 20,
        "label": "Non-empty summary string (>20 chars)",
    },
    "objections": {
        "check": lambda o: (
            len(o.get("objections", [])) >= 1
            and any(obj["category"] == "price" for obj in o["objections"])
        ),
        "label": "At least 1 objection; 'price' category present",
    },
    "call_outcome": {
        "check": lambda o: o.get("classification") == "completed_positive",
        "label": "classification == completed_positive",
    },
    "identified_problem": {
        "check": lambda p: (
            len(p.get("pain_points", [])) >= 1
            and any(
                pp["category"] in ("cost", "renewal") for pp in p.get("pain_points", [])
            )
        ),
        "label": "At least 1 pain point; 'cost' or 'renewal' present",
    },
    "service_issues": {
        "check": lambda s: (
            len(s.get("issues", [])) >= 1
            and any(iss["source"] == "current_provider" for iss in s.get("issues", []))
        ),
        "label": "At least 1 issue with source=current_provider (La Caja)",
    },
    "commitments": {
        "check": lambda c: (
            len(c.get("commitments", [])) >= 1
            and any(cm["type"] == "receive_quote" for cm in c.get("commitments", []))
        ),
        "label": "At least 1 commitment; 'receive_quote' type present",
    },
    "detected_interests": {
        "check": lambda i: (
            len(i.get("items", [])) >= 1
            and any(
                item["product"] == "auto_todo_riesgo" for item in i.get("items", [])
            )
        ),
        "label": "At least 1 interest; 'auto_todo_riesgo' detected",
    },
    "interest_level": {
        "check": lambda il: isinstance(il, int) and il >= 50,
        "label": "interest_level >= 50 (high engagement + quote request)",
    },
    "profile_facts": {
        "check": lambda pf: len(pf.get("updates", [])) >= 1,
        "label": "At least 1 profile fact update (occupation/decision_style)",
    },
    "misc_notes": {
        "check": lambda mn: len(mn.get("notes", [])) >= 1,
        "label": "At least 1 misc note generated",
    },
    "data_corrections_structured": {
        "check": lambda dc: (
            len(dc.get("corrections", [])) >= 1
            and any(
                c["field"] in ("car_model", "car_year")
                for c in dc.get("corrections", [])
            )
        ),
        "label": "At least 1 correction (car_model or car_year fix)",
    },
    "next_action_result": {
        "check": lambda na: na.get("action") in ("follow_up", "schedule_call"),
        "label": "action == follow_up or schedule_call",
    },
}

# ---------------------------------------------------------------------------
# Transcript 2: NEGATIVE — Hostile/rejection, abandonment, abrupt ending
# ---------------------------------------------------------------------------

TRANSCRIPT_NEGATIVE = """\
Agente: Hola, buenas tardes. Habla Jaumpablo de Quintana Seguros. ¿Hablo con Ricardo Gómez?
Lead: Sí, ¿qué querés?
Agente: ¿Cómo estás Ricardo? Te llamaba porque consultaste por...
Lead: Pará, pará. Yo no consulté nada. Me están llamando todo el día de distintas empresas, me tienen harto.
Agente: Disculpá Ricardo, tenemos tu contacto de una consulta web. Solo quería ofrecerte...
Lead: No me interesa. Ya tengo seguro y no quiero cambiar. Estoy bien con el que tengo.
Agente: Entiendo perfectamente. ¿Puedo preguntarte con quién estás actualmente? Capaz te podemos ofrecer algo mejor...
Lead: Estoy con Federación Patronal y estoy perfecto. No necesito nada. Aparte los seguros están todos caros, es un robo lo que cobran. No me interesa pagar más de lo que ya pago.
Agente: Te entiendo. Mirá, nosotros muchas veces logramos precios más competitivos que...
Lead: Mirá hermano, te lo digo bien: no me llamen más. No me interesa, no quiero que me llamen nunca más. Si me vuelven a llamar me voy a quejar. ¿Quedó claro?
Agente: Sí, perfectamente Ricardo. Te sacamos de la lista de contacto. Disculpá la molestia.
Lead: Bien. Chau."""

EXPECTED_NEGATIVE = {
    "summary": {
        "check": lambda s: isinstance(s, str) and len(s) > 20,
        "label": "Non-empty summary string",
    },
    "objections": {
        "check": lambda o: (
            len(o.get("objections", [])) >= 1
            and any(
                obj["category"] == "hard_rejection" for obj in o.get("objections", [])
            )
        ),
        "label": "At least 1 objection; 'hard_rejection' present",
    },
    "call_outcome": {
        "check": lambda o: o.get("classification")
        in ("do_not_contact", "completed_negative"),
        "label": "classification == do_not_contact or completed_negative",
    },
    "identified_problem": {
        "check": lambda p: True,  # May or may not have pain points
        "label": "Any valid output (pain_points may be empty for hostile call)",
    },
    "service_issues": {
        "check": lambda s: True,  # Should be empty — no service complaint from OUR side
        "label": "Any valid output (likely empty)",
    },
    "commitments": {
        "check": lambda c: len(c.get("commitments", [])) == 0,
        "label": "No commitments (hostile rejection)",
    },
    "detected_interests": {
        "check": lambda i: len(i.get("items", [])) == 0,
        "label": "No interests detected (explicit rejection)",
    },
    "interest_level": {
        "check": lambda il: isinstance(il, int) and il <= 20,
        "label": "interest_level <= 20 (no interest at all)",
    },
    "profile_facts": {
        "check": lambda pf: True,  # May detect personality_tone
        "label": "Any valid output (might detect personality traits)",
    },
    "misc_notes": {
        "check": lambda mn: True,  # Might note caution
        "label": "Any valid output (might note caution/tone)",
    },
    "data_corrections_structured": {
        "check": lambda dc: len(dc.get("corrections", [])) == 0,
        "label": "No corrections (no data mentioned)",
    },
    "next_action_result": {
        "check": lambda na: na.get("action") == "close_lead",
        "label": "action == close_lead (do_not_contact or hard_rejection)",
    },
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_analysis(transcript: str, label: str) -> dict[str, Any]:
    """Run the full analysis pipeline on a transcript and return facts dict."""
    from app.summarizer import _call_gpt_summarize
    from app.analysis.universal.next_action import LeadSnapshot, ClientRules

    # Simulate a lead with some data for data_corrections to work with
    current_lead_data = {
        "name": "Martín Rodríguez" if "Martín" in transcript else "Ricardo Gómez",
        "phone": "+5491155551234",
        "email": None,
        "age": None,
        "car_make": "Toyota" if "Toyota" in transcript else None,
        "car_model": "Corolla"
        if "Corolla" in transcript
        else None,  # Wrong! Should be Corolla Cross
        "car_year": 2022 if "2022" in transcript else None,  # Wrong! Should be 2023
        "current_insurance": "La Caja" if "La Caja" in transcript else None,
    }

    # Simulate lead state
    lead_snapshot = LeadSnapshot(
        call_count=1,
        do_not_call=False,
        last_called_at=None,
    )

    # Simulate client rules
    client_rules = ClientRules(
        max_attempts=5,
        min_interest_for_followup=40,
        close_on_hard_rejection=True,
        scheduler_cooldown_minutes=60,
        scheduler_allowed_hours_start=9,
        scheduler_allowed_hours_end=20,
        scheduler_timezone="America/Argentina/Buenos_Aires",
    )

    print(f"\n{'='*80}")
    print(f"🧪 RUNNING ANALYSIS: {label}")
    print(f"{'='*80}")
    print(f"Transcript length: {len(transcript)} chars")
    print("Calling GPT (this takes 10-30 seconds)...")

    start = time.time()
    summary, facts = await _call_gpt_summarize(
        transcript,
        previous_interest_level=None,
        current_profile_facts=[],
        current_misc_notes=[],
        current_lead_data=current_lead_data,
        has_lead=True,
        lead_snapshot=lead_snapshot,
        client_rules=client_rules,
    )
    elapsed = time.time() - start

    print(f"✅ Analysis completed in {elapsed:.1f}s")

    # Rebuild the full facts dict with summary re-added
    facts["summary"] = summary
    return facts


def validate_results(facts: dict, expectations: dict, label: str) -> tuple[int, int]:
    """Validate results against expectations. Returns (passed, total)."""
    print(f"\n{'─'*80}")
    print(f"📋 VALIDATION RESULTS: {label}")
    print(f"{'─'*80}")

    passed = 0
    total = 0

    for key, expectation in expectations.items():
        total += 1
        value = facts.get(key)

        # Handle special serialization cases
        if value is None:
            display_val = "None"
            result = False
        else:
            # Convert Pydantic models to dicts for validation
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            display_val = json.dumps(value, ensure_ascii=False, default=str)[:200]

            try:
                result = expectation["check"](value)
            except Exception as e:
                result = False
                display_val = f"ERROR: {e}"

        status = "✅" if result else "❌"
        if result:
            passed += 1

        print(f"  {status} {key}")
        print(f"       Expected: {expectation['label']}")
        if not result:
            print(f"       Got: {display_val}")
        print()

    return passed, total


def print_captured_calls(scenario_label: str, start_idx: int):
    """Print captured GPT calls for a scenario."""
    calls = _captured_calls[start_idx:]
    print(f"\n{'─'*80}")
    print(f"🔍 CAPTURED GPT CALLS: {scenario_label} ({len(calls)} calls)")
    print(f"{'─'*80}")

    for i, call in enumerate(calls, 1):
        print(f"\n  ┌── Call #{i} ({call['method']})")
        print(f"  │ Model: {call['model']}")
        print(f"  │ Duration: {call['duration_ms']}ms")

        # Print system prompt (first message)
        messages = call.get("messages", [])
        for msg in messages:
            if msg["role"] == "system":
                prompt_preview = msg["content"][:500]
                if len(msg["content"]) > 500:
                    prompt_preview += f"\n  │   ... [{len(msg['content'])} chars total]"
                print("  │ System prompt:")
                for line in prompt_preview.split("\n"):
                    print(f"  │   {line}")

        if call.get("response_format"):
            print(f"  │ Response format: {call['response_format']}")

        # Response preview
        resp = call.get("response_preview", "")
        if resp:
            print(f"  │ Response: {resp[:300]}")

        print("  └──")


def save_full_capture(output_dir: Path):
    """Save the full capture to a JSON file for detailed review."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = (
        output_dir
        / f"smoke_test_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    # Sanitize messages for JSON serialization
    serializable_calls = []
    for call in _captured_calls:
        c = dict(call)
        # Messages are already dicts, just ensure serializable
        serializable_calls.append(c)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(serializable_calls, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n💾 Full capture saved to: {output_file}")
    return output_file


async def main():
    """Run smoke tests for both scenarios."""
    from openai import AsyncOpenAI
    from app.core.config import Settings

    settings = Settings()
    api_key = settings.openai_api_key.get_secret_value()

    # Create the real client
    real_client = AsyncOpenAI(api_key=api_key)

    # Monkey-patch the client to intercept calls
    original_parse = real_client.beta.chat.completions.parse
    original_create = real_client.chat.completions.create

    intercepted_parse, intercepted_create = _make_interceptor(
        original_parse, original_create
    )

    real_client.beta.chat.completions.parse = intercepted_parse
    real_client.chat.completions.create = intercepted_create

    # Patch _get_openai_client to return our instrumented client
    with patch(
        "app.summarizer._get_openai_client",
        return_value=(real_client, "gpt-4o-mini"),
    ):
        print("\n" + "█" * 80)
        print("█  QORA UNIVERSAL ANALYSIS — SMOKE TEST")
        print("█  13 dimensions × 2 scenarios = full pipeline validation")
        print("█" * 80)

        # --- Scenario 1: Positive call ---
        start_idx_1 = len(_captured_calls)
        facts_positive = await run_analysis(
            TRANSCRIPT_POSITIVE, "Scenario 1: POSITIVE (complete call, high interest)"
        )
        passed_1, total_1 = validate_results(
            facts_positive, EXPECTED_POSITIVE, "Scenario 1: POSITIVE"
        )
        print_captured_calls("Scenario 1: POSITIVE", start_idx_1)

        # --- Scenario 2: Negative call ---
        start_idx_2 = len(_captured_calls)
        facts_negative = await run_analysis(
            TRANSCRIPT_NEGATIVE, "Scenario 2: NEGATIVE (hostile rejection)"
        )
        passed_2, total_2 = validate_results(
            facts_negative, EXPECTED_NEGATIVE, "Scenario 2: NEGATIVE"
        )
        print_captured_calls("Scenario 2: NEGATIVE", start_idx_2)

        # --- Summary ---
        total_passed = passed_1 + passed_2
        total_checks = total_1 + total_2

        print(f"\n{'═'*80}")
        print("📊 FINAL SUMMARY")
        print(f"{'═'*80}")
        print(f"  Scenario 1 (Positive): {passed_1}/{total_1} checks passed")
        print(f"  Scenario 2 (Negative): {passed_2}/{total_2} checks passed")
        print("  ────────────────────────────────────")
        print(f"  TOTAL: {total_passed}/{total_checks} checks passed")
        print(f"  Total GPT calls: {len(_captured_calls)}")
        total_time = sum(c.get("duration_ms", 0) for c in _captured_calls)
        print(f"  Total GPT time: {total_time/1000:.1f}s")
        print()

        if total_passed == total_checks:
            print("  🎉 ALL CHECKS PASSED — Pipeline is working correctly!")
        else:
            print(f"  ⚠️  {total_checks - total_passed} check(s) failed — review needed")

        # Save full capture
        output_dir = Path(__file__).resolve().parent.parent / "test_outputs"
        save_full_capture(output_dir)

        # Also save the facts for manual inspection
        facts_file = (
            output_dir
            / f"smoke_test_facts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(facts_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "scenario_1_positive": facts_positive,
                    "scenario_2_negative": facts_negative,
                },
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        print(f"💾 Full facts saved to: {facts_file}")

        return total_passed == total_checks


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
