# Post-Call Analysis Pipeline

After every call ends, Qora runs a fully asynchronous analysis pipeline that extracts structured intelligence from the transcript. The pipeline fans out 11 independent analysis dimensions in parallel (plus 3 stateful pipelines), then feeds all results into a `next_action` decision engine. It runs as an `asyncio.create_task` after the session closes — it **never blocks the call**, and any failure is caught and stored as a partial-failure marker.

---

## Table of Contents

1. [How It's Triggered](#1-how-its-triggered)
2. [Pipeline Architecture](#2-pipeline-architecture)
3. [Graceful Degradation](#3-graceful-degradation)
4. [Analysis Language](#4-analysis-language)
5. [The 11 Dimensions — Quick Reference](#5-the-11-dimensions--quick-reference)
6. [Dimension Details](#6-dimension-details)
   - [summary](#61-summary)
   - [outcome](#62-outcome)
   - [interests + interest_level](#63-interests--interest_level)
   - [commitments](#64-commitments)
   - [objections](#65-objections)
   - [problem](#66-problem)
   - [service_issues](#67-service_issues)
   - [profile_facts](#68-profile_facts)
   - [misc_notes](#69-misc_notes)
   - [data_corrections](#610-data_corrections)
   - [next_action](#611-next_action)
7. [Storage Architecture](#7-storage-architecture)

---

## 1. How It's Triggered

The pipeline is triggered in two ways:

| Trigger | Endpoint | When |
|---------|----------|------|
| Frontend close | `POST /calls/{id}/end` | Browser calls this when WebSocket closes with code `1000` |
| ElevenLabs webhook | `POST /api/v1/calls/elevenlabs-postcall` | ElevenLabs sends this after the conversation ends |

In both cases, `generate_summary_and_facts()` is scheduled via `asyncio.create_task`.

> **Note on ElevenLabs webhook:** If the session was already `completed`, any extra turns from ElevenLabs are merged into the transcript before the summarizer is re-triggered.

---

## 2. Pipeline Architecture

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

**Orchestrator**: `backend/app/summarizer.py`  
**Model**: `gpt-4o-mini` with structured outputs (Pydantic + OpenAI `beta.chat.completions.parse`)

---

## 3. Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| One dimension throws | `return_exceptions=True` captures the error — other dimensions unaffected |
| Stateful pipeline throws | Catches all internal exceptions, returns empty results — never raises |
| All dimensions fail | Writes a partial-failure `CallAnalysis` row with `analysis_status="failed"` |
| `next_action` pipeline fails | Non-critical — `next_action_suggested` defaults to `None` |

---

## 4. Analysis Language

All **text-valued** fields (e.g. `reason`, `description`, `evidence`, `note`) are written in the client's configured `analysis_language` (default: `"Spanish"`).

**Canonical code fields** (`classification`, `category`, `confidence`, `operation`, etc.) always remain as English codes regardless of the language setting.

---

## 5. The 11 Dimensions — Quick Reference

| # | Dimension | Module | Type | What It Extracts |
|---|-----------|--------|------|------------------|
| 1 | `summary` | `universal/summary.py` | Stateless | One sentence: what happened on the call |
| 2 | `outcome` | `universal/outcome.py` | Stateless | Semantic call classification + abandonment analysis |
| 3 | `interests` | `universal/interest/interests.py` | Sequential (2-agent) | Product interests + specific needs per product |
| 4 | `interest_level` | `universal/interest/interest_level.py` | Sequential (2-agent) | 0–100 engagement score + signals |
| 5 | `commitments` | `universal/commitments.py` | Stateless | Bilateral commitments and next steps made on the call |
| 6 | `objections` | `universal/objections.py` | Stateless | Concerns and pushback raised; how the agent handled them |
| 7 | `problem` | `universal/problem.py` | Stateless | Underlying pain points that motivate the lead's interest |
| 8 | `service_issues` | `universal/service_issues.py` | Stateless | Specific service complaints about past or current providers |
| 9 | `profile_facts` | `universal/profile_facts.py` | Stateful | Stable personality traits; persisted as `add/update/remove` ops |
| 10 | `misc_notes` | `universal/misc_notes.py` | Stateful | Temporal/operational context for the next call (sliding window) |
| 11 | `data_corrections` | `universal/data_corrections.py` | Stateful | Explicit corrections to lead personal data made during the call |
| — | `next_action` | `universal/next_action.py` | Post-analysis | Next action decision from rules engine + GPT validation |

---

## 6. Dimension Details

### 6.1 `summary`

**Extracts**: A single sentence describing what happened during the call — factual, third-person, no opinions.

**Output schema**:
```python
class SummaryAxis(BaseModel):
    text: str  # max ~40 tokens
```

**Stored in**: `CallSession.summary`, `CallAnalysis.summary`

---

### 6.2 `outcome`

**Extracts**: Semantic classification of how the call went, including abandonment analysis.

**Output schema**:
```python
class CallOutcome(BaseModel):
    classification: Literal[
        "no_answer", "busy", "callback_requested",
        "completed_positive", "completed_neutral", "completed_negative",
        "do_not_contact", "wrong_number", "hostile", "confused", "technical_issue"
    ]
    reason: str                    # one sentence (in analysis_language)
    confidence: Literal["low", "medium", "high"]
    was_abrupt: bool | None        # null for completed/callback outcomes
    abandonment_trigger: Literal[
        "price_shock", "lost_patience", "external_interruption",
        "objection_escalation", "no_interest", "technical_failure",
        "time_constraint", "other"
    ] | None                       # null for completed/callback outcomes
```

**Business rules**:
- `was_abrupt` and `abandonment_trigger` are automatically `None` for `completed_positive`, `completed_neutral`, `completed_negative`, and `callback_requested` (enforced by Pydantic `model_validator`).
- `do_not_contact` classification sets `Lead.do_not_call = True`.

**Stored in**: `CallAnalysis.classification`, `.outcome_reason`, `.was_abrupt`, `.abandonment_trigger`; `Lead.extracted_facts["call_outcome"]`

---

### 6.3 `interests` + `interest_level`

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

**Agent 2 — Interest Level** (`interest_level.py`): Scores overall lead engagement on a 0–100 scale.

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

| Situation | Formula |
|-----------|---------|
| First call (no previous score) | `max(product_scores)` — 100% current signal |
| Subsequent calls | `round(max(product_scores) * 0.7 + previous * 0.3)` — 70/30 exponential smoothing |

**Stored in**: `CallAnalysis.products`, `.specific_needs`; `Lead.interest_level`; `LeadInterestHistory`

---

### 6.4 `commitments`

**Extracts**: Concrete bilateral commitments and next-step actions made during the call (e.g. "agent will send a quote", "lead will consult their partner").

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

**Business rules**:
- `callback` commitments (strength=strong/medium, owner=lead/both) → trigger `schedule_call` in the `next_action` pipeline.
- `receive_quote` commitments → trigger `follow_up`.

**Stored in**: `CallAnalysis.commitment_signals`; `Lead.extracted_facts["commitments"]`

---

### 6.5 `objections`

**Extracts**: Concerns, hesitations, and pushback raised by the lead. Tracks how the agent handled each objection.

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

**Business rules**:
- Unresolved `hard_rejection` with `strength=high` + client's `close_on_hard_rejection=True` → `close_lead` action.
- Objection categories are **unioned** across calls in `Lead.objections_heard` (not replaced).

**Stored in**: `CallAnalysis.objections`; `Lead.objections_heard` (union)

---

### 6.6 `problem`

**Extracts**: Underlying pain points and unmet needs that motivate the lead's interest.

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

**Boundary rules** (to avoid overlap with other dimensions):

| Category value | When to use here | When NOT to use here |
|----------------|-----------------|---------------------|
| `bad_experience` | General past experience that motivates exploration | Specific service complaint → use `service_issues` |
| `cost` | Background cost concern driving exploration | Active price negotiation → use `objections` |

**Stored in**: `CallAnalysis.pain_points`, `.urgency`, `.primary_need`; `Lead.extracted_facts["identified_problem"]`

---

### 6.7 `service_issues`

**Extracts**: Specific service complaints about current, previous, or our own insurance providers.

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

### 6.8 `profile_facts`

**Extracts**: Stable personality traits, preferences, and lifestyle attributes about the lead. These persist across calls via the `LeadProfileFact` table.

**Architecture**: Stateful pipeline (`run_profile_facts_pipeline`). Receives the lead's current active profile facts and returns `add/update/remove` operations.

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

**Boundary rule**: Profile facts = **stable traits** (e.g. "consults partner before decisions"). NOT temporal context (→ `misc_notes`), NOT product interests (→ `interests`), NOT service complaints (→ `service_issues`).

**Validation edge cases**:
- `update/remove` operations with invalid `target_fact_id` are silently demoted to `add`.
- Operations on first call (no current facts) are filtered to `add` only.

**Stored in**: `LeadProfileFact` table (upsert/supersede semantics); `CallAnalysis.profile_facts`

---

### 6.9 `misc_notes`

**Extracts**: Temporal and operational context for the agent's next call. Managed as a sliding window — old, expired, or resolved notes are dropped; new ones are added.

**Architecture**: Stateful pipeline (`run_misc_notes_pipeline`). Receives previous notes from `Lead.extracted_facts["misc_notes"]` and outputs the **full updated list** (not a diff).

**Output schema**:
```python
class MiscNote(BaseModel):
    type: Literal[
        "continuity",        # context that should persist across calls
        "pending_topic",     # something unresolved from this call
        "tone_context",      # emotional tone / communication style
        "temporary_context", # transient fact (upcoming event, time constraint)
        "caution",           # warning about lead behavior or sensitivity
        "other"
    ]
    note: str  # one sentence, max ~100 chars (in analysis_language)

class MiscNotesAxis(BaseModel):
    notes: list[MiscNote]  # max 5, prefer 3
```

**Boundary rule**: Misc notes = **temporal/operational** context. NOT stable personality traits (→ `profile_facts`).

**Stored in**: `Lead.extracted_facts["misc_notes"]`; `CallAnalysis.misc_notes`; injected into memory context as `--- Notas operativas ---` section

---

### 6.10 `data_corrections`

**Extracts**: Explicit corrections the lead made to their personal data during the call (e.g. "actually my car year is 2019, not 2018").

**Architecture**: Stateful pipeline (`run_data_corrections_pipeline`). Receives the current lead field snapshot and returns validated corrections.

**Correctable fields**: `name`, `phone`, `email`, `age`, `car_make`, `car_model`, `car_year`, `current_insurance`

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

**Post-processing validation gates** (applied in order):

| Gate | Rule |
|------|------|
| 1. Registry lookup | Unknown fields are silently dropped |
| 2. Idempotency | If `corrected_value == current_value` → dropped |
| 3. Per-field validation | phone (≥10 digits), email (RFC 5322), car_year (1900–2030), age (1–120) |
| 4. Confidence gate | Currently disabled (`threshold=0.0` — all valid corrections auto-apply) |

Applied corrections are written to the `Lead` column directly via `setattr`. Also stored as `LeadProfileFact` rows for audit trail.

**Stored in**: `Lead` direct columns (if applied); `CallAnalysis.data_corrections` (JSON list of all corrections with `applied` flag)

---

### 6.11 `next_action`

**Architecture**: Post-analysis sequential pipeline (`run_next_action_pipeline`). Runs **after** all parallel dimensions complete. Receives structured dimension outputs — NOT the transcript.

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

**Decision flow** (strict priority, first match wins):

| Priority | Condition | Action |
|----------|-----------|--------|
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

## 7. Storage Architecture

All analysis outputs are written atomically inside a single DB savepoint (nested transaction):

```python
async with db.begin_nested():        # savepoint
    cs.summary = summary
    cs.extracted_facts = facts
    await _merge_facts_into_lead()
    await _upsert_call_analysis()
    await _auto_schedule_if_needed()
```

If any write fails, the savepoint rolls back — no partial data is committed.

### Dual-Write Pattern

Analysis is stored in two places for different access patterns:

| Store | Purpose |
|-------|---------|
| `CallSession.extracted_facts` (JSON blob) | Backward compatibility and raw fact access |
| `CallAnalysis` table (normalized columns) | Structured queries, analytics, indexing — **authoritative for analytics** |

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
