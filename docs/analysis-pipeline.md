# QORA — Post-Call Analysis Pipeline

## Overview

After every call ends, QORA runs a fully asynchronous analysis pipeline that extracts structured intelligence from the transcript. The pipeline is orchestrated by `backend/app/summarizer.py` and uses `gpt-4o-mini` with structured outputs (Pydantic + OpenAI `beta.chat.completions.parse`).

The pipeline never blocks the call. It runs as an `asyncio.create_task` after the session closes, and **any failure in the pipeline must never affect the call itself** — all errors are caught, logged, and stored as partial-failure markers.

## Triggering the Pipeline

The pipeline is triggered in two ways:

1. **Frontend `/calls/{id}/end`** — The browser calls this endpoint when the WebSocket closes (code `1000`). `close_session()` schedules `generate_summary_and_facts()` via `asyncio.create_task`.
2. **ElevenLabs post-call webhook** — ElevenLabs sends a `POST /api/v1/calls/elevenlabs-postcall` after the conversation ends. If the session was previously closed (status = `completed`), any extra turns from ElevenLabs are merged and the summarizer is re-triggered on the updated transcript.

## Architecture: Fan-Out Pipeline

```
transcript_text
       │
       ├──► asyncio.gather (parallel) ──────────────────────────────────┐
       │         │                                                        │
       │    6 independent                                                 │
       │    dimension coroutines                                          │
       │    (summary, outcome,                                            │
       │     commitments, objections,                                     │
       │     problem, service_issues)                                     │
       │                                                                  │
       ├──► run_interest_pipeline() ──────── sequential ─────────────────┤
       │         Agent 1 (interests)                                      │
       │              ↓                                                   │
       │         Agent 2 (interest_level)                                 │
       │                                                                  │
       ├──► run_profile_facts_pipeline() ─── stateful ───────────────────┤
       │    (uses current LeadProfileFact rows)                           │
       │                                                                  │
       ├──► run_misc_notes_pipeline() ─────── stateful ──────────────────┤
       │    (uses previous misc_notes from Lead.extracted_facts)          │
       │                                                                  │
       └──► run_data_corrections_pipeline() ─ stateful ──────────────────┘
            (uses current Lead field snapshot)
                                        │
                        (all parallel phases complete)
                                        │
                                        ▼
                            next_action pipeline (sequential)
                            assembles NextActionContext from
                            all dimension outputs + lead state
                            → runs rules engine (P1-P5)
                            → GPT validates rules decision
                            → NextActionResult
                                        │
                                        ▼
                            PostCallAnalysis.model_dump()
                                        │
                           ┌────────────┴─────────────────┐
                           ▼                               ▼
                    CallSession update              CallAnalysis upsert
                    (summary + extracted_facts)     (normalized columns)
                           │
                    Lead.merge()
                    (interest_level, objections,
                     do_not_call, next_action,
                     next_action_at)
                           │
                    LeadProfileFact rows
                    LeadInterestHistory row
                           │
                    auto_schedule() if needed
```

## Graceful Degradation

- Each dimension runs in its own coroutine. If one throws, `return_exceptions=True` captures the error — the other dimensions are unaffected.
- Stateful pipelines (`profile_facts`, `misc_notes`, `data_corrections`) catch all internal exceptions and return empty results — they **never raise**.
- If **all** dimensions fail, a partial-failure `CallAnalysis` row is written with `analysis_status="failed"`.
- The `next_action` pipeline failure is non-critical — the `next_action_suggested` field defaults to `None`.

## Analysis Language

All text-valued fields in each dimension (e.g. `reason`, `description`, `evidence`, `note`) are written in the client's configured `analysis_language` (default: `"Spanish"`). Canonical code fields (`classification`, `category`, `confidence`, `operation`, etc.) always stay as English codes regardless of language setting.

---

## The 11 Universal Dimensions

### 1. `summary` (`universal/summary.py`)

**What it extracts**: A single sentence describing what happened during the call — factual, third-person, no opinions.

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class SummaryAxis(BaseModel):
    text: str  # max ~40 tokens
```

**Stored in**: `CallSession.summary`, `CallAnalysis.summary`

---

### 2. `outcome` (`universal/outcome.py`)

**What it extracts**: Semantic classification of how the call went, including abandonment analysis.

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class CallOutcome(BaseModel):
    classification: Literal[
        "no_answer", "busy", "callback_requested",
        "completed_positive", "completed_neutral", "completed_negative",
        "do_not_contact", "wrong_number", "hostile", "confused", "technical_issue"
    ]
    reason: str          # one sentence (in analysis_language)
    confidence: Literal["low", "medium", "high"]
    was_abrupt: bool | None    # null for completed/callback outcomes
    abandonment_trigger: Literal[
        "price_shock", "lost_patience", "external_interruption",
        "objection_escalation", "no_interest", "technical_failure",
        "time_constraint", "other"
    ] | None                   # null for completed/callback outcomes
```

**Business rules**:
- `was_abrupt` and `abandonment_trigger` are automatically set to `None` for `completed_positive`, `completed_neutral`, `completed_negative`, and `callback_requested` outcomes (enforced by Pydantic `model_validator`).
- `do_not_contact` classification sets `Lead.do_not_call = True`.

**Stored in**: `CallAnalysis.classification`, `.outcome_reason`, `.was_abrupt`, `.abandonment_trigger`; `Lead.extracted_facts["call_outcome"]`

---

### 3. `interests` + `interest_level` (`universal/interest/`)

**Architecture**: Two-agent sequential pipeline (`run_interest_pipeline`).

**Agent 1 — Interests** (`interests.py`): Detects which insurance products the lead expressed interest in and the specific needs behind each product.

```python
class InterestItem(BaseModel):
    product: str       # from PRODUCT_CATALOG (e.g. "auto", "hogar", "vida")
    needs: list[str]   # from NEED_TAGS catalog, max 3
    evidence: str      # direct transcript quote
    confidence: Literal["low", "medium", "high"]

class InterestsAxis(BaseModel):
    items: list[InterestItem]  # max 5
```

**Agent 2 — Interest Level** (`interest_level.py`): Scores the overall lead engagement on a 0–100 scale.

```python
class InterestLevelResult(BaseModel):
    per_product: list[ProductScore]     # per-product scores (product, score, reason)
    general_score: int                  # 0-100 (formula-computed, not LLM)
    level: Literal["very_low", "low", "medium", "high", "very_high"]
    reason: str                         # 1-sentence overall explanation
    positive_signals: list[str]         # up to 3 signals indicating positive interest
    negative_signals: list[str]         # up to 3 signals indicating hesitation
    confidence: Literal["low", "medium", "high"]
```

**Score formula**:
- With previous score: `round(max(product_scores) * 0.7 + previous * 0.3)` (70/30 exponential smoothing)
- Without previous: `max(product_scores)` (first call — 100% current signal)

**Stored in**: `CallAnalysis.products`, `.specific_needs`; `Lead.interest_level`; `LeadInterestHistory`

---

### 4. `commitments` (`universal/commitments.py`)

**What it extracts**: Concrete bilateral commitments and next-step actions made during the call (e.g. "agent will send a quote", "lead will consult their partner").

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class Commitment(BaseModel):
    type: Literal[
        "send_document", "receive_quote", "review_proposal",
        "consult_third_party", "callback", "continue_by_channel",
        "compare_options", "other"
    ]
    owner: Literal["lead", "agent", "both"]
    description: str       # 1-2 sentences (in analysis_language)
    due: Literal["today", "tomorrow", "this_week", "specific_date", "unknown"]
    strength: Literal["weak", "medium", "strong"]
    evidence: str          # direct transcript quote
    confidence: Literal["low", "medium", "high"]

class CommitmentsAxis(BaseModel):
    commitments: list[Commitment]  # max 5
```

**Business rules**: `callback` commitments (strength=strong/medium, owner=lead/both) trigger `schedule_call` in the `next_action` pipeline. `receive_quote` commitments trigger `follow_up`.

**Stored in**: `CallAnalysis.commitment_signals`; `Lead.extracted_facts["commitments"]`

---

### 5. `objections` (`universal/objections.py`)

**What it extracts**: Concerns, hesitations, and pushback raised by the lead. Tracks how the agent handled each objection.

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class Objection(BaseModel):
    category: Literal[
        "price", "current_provider", "timing", "authority", "trust", "need",
        "information_gap", "coverage_or_product_fit", "payment_or_budget",
        "documentation_or_data", "channel_preference", "bad_experience",
        "hard_rejection", "other"
    ]
    strength: Literal["low", "medium", "high"]
    resolution_status: Literal["resolved", "partially_resolved", "unresolved", "bypassed", "unknown"]
    evidence: str          # direct transcript quote
    description: str       # 1-2 sentences (in analysis_language)
    confidence: Literal["low", "medium", "high"]
    agent_response_summary: str  # how the agent handled it
    is_primary: bool       # at most 1 per call

class ObjectionsAxis(BaseModel):
    objections: list[Objection]  # max 5
```

**Business rules**: Unresolved `hard_rejection` with `strength=high` + client's `close_on_hard_rejection=True` → `close_lead` action. Objection categories are unioned across calls in `Lead.objections_heard` (not replaced).

**Stored in**: `CallAnalysis.objections`; `Lead.objections_heard` (union)

---

### 6. `problem` (`universal/problem.py`)

**What it extracts**: Underlying pain points and unmet needs that motivate the lead's interest.

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class PainPoint(BaseModel):
    category: Literal[
        "cost", "coverage", "renewal", "bad_experience", "lack_of_clarity",
        "new_need", "risk_exposure", "comparison", "deadline", "dissatisfaction", "other"
    ]
    description: str       # 1-2 sentences (in analysis_language)
    evidence: str          # direct transcript quote
    urgency: Literal["low", "medium", "high", "unknown"]
    confidence: Literal["low", "medium", "high"]
    is_primary: bool       # at most 1 per call

class ProblemAxis(BaseModel):
    pain_points: list[PainPoint]  # max 5
```

**Boundary rules**:
- `bad_experience` = a general past experience that motivates exploration (NOT a specific service complaint → that goes to `service_issues`)
- `cost` = a background cost concern that drives exploration (NOT active price negotiation → that goes to `objections`)

**Stored in**: `CallAnalysis.pain_points`, `.urgency`, `.primary_need`; `Lead.extracted_facts["identified_problem"]`

---

### 7. `service_issues` (`universal/service_issues.py`)

**What it extracts**: Specific service complaints about current, previous, or our own insurance providers.

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class ServiceIssue(BaseModel):
    category: Literal[
        "poor_attention", "delay", "lack_of_response", "lack_of_clarity",
        "claim_problem", "billing_issue", "administrative_problem",
        "bad_experience", "communication_problem", "other"
    ]
    description: str       # 1-2 sentences (in analysis_language)
    source: Literal["current_provider", "previous_provider", "our_company", "unknown"]
    severity: Literal["low", "medium", "high"]
    evidence: str          # direct transcript quote
    confidence: Literal["low", "medium", "high"]

class ServiceIssuesAxis(BaseModel):
    issues: list[ServiceIssue]  # max 5
```

**Stored in**: `CallAnalysis.service_issues`; `Lead.extracted_facts["service_issues"]`

---

### 8. `profile_facts` (`universal/profile_facts.py`)

**What it extracts**: Stable personality traits, preferences, and lifestyle attributes about the lead. These persist across calls via the `LeadProfileFact` table.

**Architecture**: Stateful pipeline (`run_profile_facts_pipeline`). Receives the lead's current active profile facts and returns `add/update/remove` operations.

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class ProfileFactCategory(str, Enum):
    OCCUPATION = "occupation"
    AVAILABILITY = "availability"
    COMMUNICATION_PREFERENCE = "communication_preference"
    DECISION_STYLE = "decision_style"
    FAMILY_CONTEXT = "family_context"
    LIFESTYLE = "lifestyle"
    FINANCIAL_ATTITUDE = "financial_attitude"
    PRODUCT_KNOWLEDGE = "product_knowledge"
    PROVIDER_RELATIONSHIP = "provider_relationship"
    PERSONALITY_TONE = "personality_tone"
    OTHER = "other"

class ProfileFactUpdate(BaseModel):
    operation: Literal["add", "update", "remove"]
    category: ProfileFactCategory
    fact: str              # human-readable fact text (in analysis_language)
    evidence: str          # transcript quote or paraphrase (in analysis_language)
    confidence: Literal["low", "medium", "high"]
    target_fact_id: str | None  # required for update/remove

class ProfileFactsAxis(BaseModel):
    updates: list[ProfileFactUpdate]  # max 5
```

**Boundary rules**: Profile facts = **stable traits** (e.g. "consults partner before decisions"). NOT temporal context (→ misc_notes), NOT product interests (→ interests dimension), NOT service complaints (→ service_issues).

**Validation**: `update/remove` operations with invalid `target_fact_id` are silently demoted to `add`. Operations on first call (no current facts) are filtered to `add` only.

**Stored in**: `LeadProfileFact` table (upsert/supersede semantics); `CallAnalysis.profile_facts`

---

### 9. `misc_notes` (`universal/misc_notes.py`)

**What it extracts**: Temporal and operational context for the agent's next call. Managed as a sliding window — old, expired, or resolved notes are dropped; new ones are added.

**Architecture**: Stateful pipeline (`run_misc_notes_pipeline`). Receives previous notes from `Lead.extracted_facts["misc_notes"]` and outputs the **full updated list** (not a diff).

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class MiscNote(BaseModel):
    type: Literal[
        "continuity",       # context that should persist across calls
        "pending_topic",    # something unresolved from this call
        "tone_context",     # emotional tone / communication style
        "temporary_context", # transient fact (upcoming event, time constraint)
        "caution",          # warning about lead behavior or sensitivity
        "other"
    ]
    note: str  # one sentence, max ~100 chars (in analysis_language)

class MiscNotesAxis(BaseModel):
    notes: list[MiscNote]  # max 5, prefer 3
```

**Boundary rules**: Misc notes = **temporal/operational** context. NOT stable personality traits (→ profile_facts).

**Stored in**: `Lead.extracted_facts["misc_notes"]`; `CallAnalysis.misc_notes`; injected into memory context as `--- Notas operativas ---` section

---

### 10. `data_corrections` (`universal/data_corrections.py`)

**What it extracts**: Explicit corrections the lead made to their personal data during the call (e.g. "actually my car year is 2019, not 2018").

**Architecture**: Stateful pipeline (`run_data_corrections_pipeline`). Receives the current lead field snapshot and returns validated corrections.

**Correctable fields**: `name`, `phone`, `email`, `age`, `car_make`, `car_model`, `car_year`, `current_insurance`

**Model**: `gpt-4o-mini`

**Output schema**:
```python
class DataCorrection(BaseModel):
    field: str             # from CORRECTABLE_FIELDS registry
    current_value: str | None
    corrected_value: str
    confidence: float      # 0.0–1.0
    evidence: str          # verbatim quote or close paraphrase
    applied: bool          # set by post-processing, not GPT
    rejection_reason: str | None
```

**Post-processing**: Each correction goes through 4 gates:
1. **Registry lookup**: unknown fields are silently dropped
2. **Idempotency**: if `corrected_value == current_value` → dropped
3. **Per-field validation**: phone (≥10 digits), email (RFC 5322), car_year (1900–2030), age (1–120)
4. **Confidence gate**: currently disabled (`threshold=0.0` — all valid corrections auto-apply)

**Applied corrections**: Written to `Lead` column directly via `setattr`. Also stored as `LeadProfileFact` rows for audit trail.

**Stored in**: `Lead` direct columns (if applied); `CallAnalysis.data_corrections` (JSON list of all corrections with `applied` flag)

---

### 11. `next_action` (`universal/next_action.py`)

**Architecture**: Post-analysis sequential pipeline (`run_next_action_pipeline`). Runs **after** all parallel dimensions complete. Receives structured outputs, NOT the transcript.

**Model**: `gpt-4o-mini` (for GPT validation and fallback only)

**Output schema**:
```python
class NextActionResult(BaseModel):
    action: Literal["follow_up", "retry_call", "schedule_call", "close_lead", "human_review"]
    reason: str
    confidence: Literal["high", "medium", "low"]
    decided_by: Literal["rules", "gpt"]
    next_action_at: datetime | None
    priority: Literal["urgent", "normal", "low"]
```

**Decision flow (strict priority, first match wins)**:

| Priority | Rule | Action |
|----------|------|--------|
| P1 | `do_not_contact` / `wrong_number` / `hostile` classification, or `lead.do_not_call=True`, or unresolved hard rejection + `close_on_hard_rejection=True` | `close_lead` |
| P2 | `lead.call_count >= client.max_attempts` | `close_lead` |
| P3 | Strong/medium `callback` commitment (owner=lead/both) | `schedule_call` |
| P3 | Strong/medium `receive_quote` commitment | `follow_up` |
| P3 | `consult_third_party` commitment | `follow_up` |
| P4 | `no_answer` / `busy` / `technical_issue` outcome, or abrupt + `external_interruption`/`time_constraint` | `retry_call` |
| P5 | `interest_level >= min_interest` + `completed_positive/neutral` | `follow_up` |
| P5 | `interest_level < 20` + `completed_negative` | `close_lead` |
| P6 | No rule matched | GPT decides independently |

After rules fire, GPT independently validates the decision. If GPT agrees → keep the rules decision. If GPT disagrees → escalate to `human_review`.

**Stored in**: `Lead.next_action`, `Lead.next_action_at`; `CallAnalysis.next_action_suggested`; `ScheduledCall` (if `action == "schedule_call"`)

---

## Storage Architecture

All analysis outputs are written atomically inside a single DB savepoint (nested transaction):

```
async with db.begin_nested():        ← savepoint
    cs.summary = summary
    cs.extracted_facts = facts
    await _merge_facts_into_lead()
    await _upsert_call_analysis()
    await _auto_schedule_if_needed()
```

If any write fails, the savepoint rolls back — no partial data is committed.

### Dual-Write Pattern

Analysis is stored in two places for different access patterns:
- `CallSession.extracted_facts` (JSON blob) — backward compatibility and raw fact access
- `CallAnalysis` table (normalized columns) — structured queries, analytics, indexing

The `CallAnalysis` table is the authoritative target for analytics queries. `CallSession.extracted_facts` is maintained for backward compatibility and memory context injection.

### Lead Merge Strategy

| Field | Strategy |
|-------|----------|
| `interest_level` | Latest wins (overwrite) |
| `objections_heard` | Union (add new categories, never remove) |
| `extracted_facts` | Merge: new non-null values overwrite old |
| `call_outcome` | Latest wins (overwrite) |
| `detected_interests` | Latest wins (overwrite) |
| `identified_problem` | Latest wins (overwrite) |
| `do_not_call` | Latching: once `True`, never set back to `False` by analysis |
| `next_action` | Latest wins |
| `next_action_at` | Latest wins |
