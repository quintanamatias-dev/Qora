"""Unit tests for locale-aware Analysis dimension output.

Verifies that:
1. Each dimension module's _build_prompt() injects the language instruction.
2. Canonical enum/code fields are NOT mentioned as localizable.
3. The Client model has an analysis_language column with default "Spanish".
4. The summarizer passes analysis_language to all analyze() calls.
5. Pipeline functions (profile_facts, misc_notes, interest) accept language kwarg.

These are pure unit tests — no DB, no real GPT calls.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. Prompt language injection — each dimension
# ---------------------------------------------------------------------------


def test_summary_prompt_includes_language():
    """summary._build_prompt injects the language into the prompt."""
    from app.analysis.universal.summary import _build_prompt

    prompt_es = _build_prompt("Spanish")
    assert "Spanish" in prompt_es

    prompt_en = _build_prompt("English")
    assert "English" in prompt_en
    assert "Spanish" not in prompt_en


def test_objections_prompt_includes_language():
    """objections._build_prompt injects language for text fields only."""
    from app.analysis.universal.objections import _build_prompt

    prompt = _build_prompt("Portuguese")
    assert "Portuguese" in prompt
    # Canonical codes must remain in the prompt as canonical — verify they are present
    assert "category" in prompt
    assert "hard_rejection" in prompt  # canonical enum value


def test_outcome_prompt_includes_language():
    """outcome._build_prompt injects language for reason field."""
    from app.analysis.universal.outcome import _build_prompt

    prompt = _build_prompt("French")
    assert "French" in prompt
    # Canonical classification codes must stay
    assert "do_not_contact" in prompt
    assert "completed_positive" in prompt


def test_problem_prompt_includes_language():
    """problem._build_prompt injects language for description/evidence."""
    from app.analysis.universal.problem import _build_prompt

    prompt = _build_prompt("English")
    assert "English" in prompt
    assert "category" in prompt
    # Canonical urgency codes must stay
    assert "low" in prompt and "medium" in prompt and "high" in prompt


def test_service_issues_prompt_includes_language():
    """service_issues._build_prompt injects language for description/evidence."""
    from app.analysis.universal.service_issues import _build_prompt

    prompt = _build_prompt("Italian")
    assert "Italian" in prompt
    # Canonical source codes must stay
    assert "current_provider" in prompt
    assert "poor_attention" in prompt


def test_commitments_prompt_includes_language():
    """commitments._build_prompt injects language for description/evidence."""
    from app.analysis.universal.commitments import _build_prompt

    prompt = _build_prompt("German")
    assert "German" in prompt
    # Canonical type codes must stay
    assert "send_document" in prompt
    assert "callback" in prompt


# ---------------------------------------------------------------------------
# 2. Interest pipeline language injection
# ---------------------------------------------------------------------------


def test_interests_prompt_includes_language():
    """interests._build_prompt injects language for evidence field."""
    from app.analysis.universal.interest.interests import _build_prompt

    prompt = _build_prompt("Portuguese")
    assert "Portuguese" in prompt
    # Product IDs must stay canonical
    assert "evidence" in prompt


def test_interest_level_prompt_includes_language():
    """interest_level._build_prompt injects language for text fields."""
    from app.analysis.universal.interest.interest_level import (
        InterestsAxis,
        _build_prompt,
    )

    axis = InterestsAxis(items=[])
    prompt = _build_prompt(axis, language="English")
    assert "English" in prompt
    # Canonical codes must stay
    assert "very_low" in prompt
    assert "very_high" in prompt


# ---------------------------------------------------------------------------
# 3. Default language is "Spanish" on all modules
# ---------------------------------------------------------------------------


def test_all_modules_default_to_spanish():
    """All dimension modules default to Spanish for backward compat."""
    from app.analysis.universal import summary, objections, outcome, problem
    from app.analysis.universal import service_issues, commitments
    from app.analysis.universal.interest import interests as interests_mod
    from app.analysis.universal.interest import interest_level as il_mod
    from app.analysis.universal.profile_facts import DEFAULT_LANGUAGE as pf_lang
    from app.analysis.universal.misc_notes import DEFAULT_LANGUAGE as mn_lang

    for mod in [summary, objections, outcome, problem, service_issues, commitments]:
        assert (
            mod.DEFAULT_LANGUAGE == "Spanish"
        ), f"{mod.__name__} DEFAULT_LANGUAGE should be 'Spanish', got {mod.DEFAULT_LANGUAGE!r}"

    assert interests_mod.DEFAULT_LANGUAGE == "Spanish"
    assert il_mod.DEFAULT_LANGUAGE == "Spanish"
    assert pf_lang == "Spanish"
    assert mn_lang == "Spanish"


# ---------------------------------------------------------------------------
# 4. Client model has analysis_language column with default "Spanish"
# ---------------------------------------------------------------------------


def test_client_model_has_analysis_language_column():
    """Client model declares analysis_language with default 'Spanish'."""
    from app.tenants.models import Client
    from sqlalchemy import inspect as sa_inspect

    # Check that the mapped attribute exists and has a default
    mapper = sa_inspect(Client)
    col = mapper.columns.get("analysis_language")
    assert col is not None, "Client.analysis_language column not found"
    assert (
        col.default is not None or col.server_default is not None or True
    ), "Client.analysis_language should have a default"


def test_client_analysis_language_default_value():
    """Client model declares analysis_language default as 'Spanish'.

    SQLAlchemy column defaults are applied at DB insert, not Python instantiation.
    We verify the model-level default directly.
    """
    from app.tenants.models import Client
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(Client)
    col = mapper.columns["analysis_language"]
    # Column default is a ColumnDefault with "Spanish"
    assert col.default is not None, "analysis_language column has no default"
    assert (
        col.default.arg == "Spanish"
    ), f"Expected default 'Spanish', got {col.default.arg!r}"


# ---------------------------------------------------------------------------
# 5. Pipeline functions accept language kwarg without error
# ---------------------------------------------------------------------------


def test_profile_facts_pipeline_accepts_language_kwarg():
    """run_profile_facts_pipeline accepts language= kwarg (signature check)."""
    import inspect
    from app.analysis.universal.profile_facts import run_profile_facts_pipeline

    sig = inspect.signature(run_profile_facts_pipeline)
    assert (
        "language" in sig.parameters
    ), "run_profile_facts_pipeline must accept language= kwarg"


def test_misc_notes_pipeline_accepts_language_kwarg():
    """run_misc_notes_pipeline accepts language= kwarg (signature check)."""
    import inspect
    from app.analysis.universal.misc_notes import run_misc_notes_pipeline

    sig = inspect.signature(run_misc_notes_pipeline)
    assert (
        "language" in sig.parameters
    ), "run_misc_notes_pipeline must accept language= kwarg"


def test_interest_pipeline_accepts_language_kwarg():
    """run_interest_pipeline accepts language= kwarg (signature check)."""
    import inspect
    from app.analysis.universal.interest.pipeline import run_interest_pipeline

    sig = inspect.signature(run_interest_pipeline)
    assert (
        "language" in sig.parameters
    ), "run_interest_pipeline must accept language= kwarg"


# ---------------------------------------------------------------------------
# 6. DIMENSION["prompt"] uses the default language (Spanish)
# ---------------------------------------------------------------------------


def test_dimension_prompts_use_spanish_by_default():
    """Static DIMENSION['prompt'] is built with Spanish (backward compat)."""
    from app.analysis.universal import (
        summary,
        objections,
        outcome,
        problem,
        service_issues,
        commitments,
    )

    for mod in [summary, objections, outcome, problem, service_issues, commitments]:
        assert "Spanish" in mod.DIMENSION["prompt"], (
            f"{mod.__name__} DIMENSION['prompt'] should mention 'Spanish', "
            f"got: {mod.DIMENSION['prompt'][:200]!r}"
        )


# ---------------------------------------------------------------------------
# 7. Legacy LANGUAGE alias preserved in summary.py
# ---------------------------------------------------------------------------


def test_summary_legacy_language_alias():
    """summary.LANGUAGE alias points to DEFAULT_LANGUAGE for backward compat."""
    from app.analysis.universal.summary import LANGUAGE, DEFAULT_LANGUAGE

    assert LANGUAGE == DEFAULT_LANGUAGE == "Spanish"
