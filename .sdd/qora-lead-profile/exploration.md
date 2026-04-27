# Exploration: Accumulative Lead Profile (Issue #36)

## Current State

### 1. _merge_facts_into_lead (summarizer.py L288-381)
Currently does "latest wins" overwrite on `Lead.extracted_facts` JSON (`{**existing_facts, **new_facts_clean}`). Objections are the ONE exception — they union-merge with deduplication. All other facts overwrite previous values.

The function ALSO dual-writes:
- `_write_lead_profile_facts()` — writes LeadProfileFact rows for scalar facts (interest_level, current_insurance, next_action, primary_need, classification, do_not_call). Uses supersede semantics: when value changes, old row gets superseded_at=now, new row inserted. But only for THESE 6 keys.
- `_write_correction_facts()` — writes LeadProfileFact rows for data_corrections (car_make, car_model, car_year).
- `_write_interest_history()` — appends LeadInterestHistory row (append-only, never updates).

**Key gap**: `profile_facts` axis from Issue #35 (e.g., "morocha", "3 hijos", "manager at startup") is stored on CallAnalysis.profile_facts as JSON text but is NOT written to LeadProfileFact rows. Same for pain_points, buying_signals, service_issues, commitment_signals.

### 2. memory.py (build_memory_context)
Reads `Lead.extracted_facts` JSON blob and formats it as `confirmed_facts` string. Uses CallSession.summary for `call_history` (last 3 completed sessions). Does NOT read LeadProfileFact or LeadInterestHistory tables at all.

### 3. Agent Tools (tools/)
- `get_lead_details` — returns basic Lead columns (name, phone, car_*, status, call_count). Does NOT return extracted_facts, objections_heard, interest_level, or any LeadProfileFact data.
- `register_interest`, `mark_not_interested`, `schedule_followup` — action tools, not query tools.
- `dispatcher.py` — simple dict-based registry mapping name→handler.

### 4. Tool Registration (webhook.py)
Tools defined in `QORA_TOOL_DEFINITIONS` dict. OpenAI function-calling format. Enabled via `Agent.tools_enabled` / `Client.tools_enabled` JSON list. Tool execution mid-stream via `_execute_tool` → `dispatch_tool`.

### 5. Lead API (leads/router.py)
`GET /leads/{id}` returns `_lead_to_dict()` which includes extracted_facts JSON blob, interest_level, objections_heard, summary_last_call, but NOT LeadProfileFact data or LeadInterestHistory.

### 6. Models (leads/models.py)
- **LeadProfileFact**: id, lead_id, fact_key, fact_value, source_call_id, recorded_at, superseded_at. Index on (lead_id, fact_key, superseded_at).
- **LeadInterestHistory**: id, lead_id, interest_level, source_call_id, recorded_at. Index on (lead_id, recorded_at).

## Affected Areas

| File | Why |
|------|-----|
| `backend/app/summarizer.py` | Extend `_write_lead_profile_facts` to write profile_facts, pain_points, service_issues, commitment_signals, buying_signals as namespaced LeadProfileFact rows |
| `backend/app/memory.py` | `build_memory_context` must read from LeadProfileFact + LeadInterestHistory instead of Lead.extracted_facts JSON |
| `backend/app/tools/get_lead_details.py` | Return accumulated profile data from LeadProfileFact |
| `backend/app/tools/dispatcher.py` | Register new tools (get_lead_profile, get_lead_history, get_lead_pain_points) |
| `backend/app/voice/webhook.py` | Add new tool definitions to QORA_TOOL_DEFINITIONS |
| `backend/app/leads/router.py` | `_lead_to_dict` and GET /leads/{id} include profile facts + interest history |
| `backend/app/leads/service.py` | Add query functions for profile facts |

## Investigation Answers

### Q1: How does _merge_facts_into_lead work?
Lines 345-359: `{**existing_facts, **new_facts_clean}` — pure overwrite. Must change to accumulate list-type facts as namespaced LeadProfileFact rows while keeping legacy JSON path for backward compat.

### Q2: How do agent tools work?
Handler in tools/*.py → registered in dispatcher._TOOL_REGISTRY + QORA_TOOL_DEFINITIONS in webhook.py. Adding tools = write handler + register in both places.

### Q3: How does memory.py build context?
Reads Lead.extracted_facts JSON → bulleted text. Reads CallSession.summary (last 3) → dated lines. Does NOT touch LeadProfileFact or LeadInterestHistory.

### Q4: How to detect contradictions?
Supersede pattern already handles scalar facts. For list-type facts, use namespace prefix + normalized deduplication.

### Q5: How should profile_facts axis map to LeadProfileFact rows?
Each item → `fact_key="profile:{normalized_text}"`, `fact_value="{original_text}"`. Similarly: pain_points→`pain:`, service_issues→`service_issue:`, etc. Append-only (no supersede).

### Q6: Impact on voice webhook path?
Minimal. New tools register via existing pattern. Memory injection via initiation.py calls build_memory_context — upgrading that function propagates automatically.

### Q7: Existing test coverage?
Extensive for LeadProfileFact CRUD, dual-write, data_corrections, do_not_call. NO tests for memory.py reading from LeadProfileFact or accumulated profile query tools (they don't exist yet).

## Approaches

### 1. Incremental Extension (Recommended)
Keep legacy JSON, extend `_write_lead_profile_facts()` for list-type facts, update `build_memory_context()` to read LeadProfileFact, add 3 new tools, extend API.
- **Pros**: Minimal risk, follows patterns, backward compatible, well-tested foundation
- **Cons**: Lead.extracted_facts becomes redundant over time
- **Effort**: Medium

### 2. Full Migration
Stop writing Lead.extracted_facts, all reads via LeadProfileFact exclusively.
- **Pros**: Clean, single source of truth
- **Cons**: Breaking change, higher risk, needs data migration
- **Effort**: High

### 3. Hybrid with Computed View
Continue dual-write, recompute Lead.extracted_facts from active LeadProfileFact after each write.
- **Pros**: Both paths work, single truth is LeadProfileFact
- **Cons**: Extra computation, complexity
- **Effort**: Medium-High

## Recommendation

**Approach 1: Incremental Extension.** The existing dual-write pattern from #34 provides the foundation. Main work: (a) write MORE fact types to LeadProfileFact, (b) read FROM LeadProfileFact in memory.py and tools, (c) add new query tools. Lead.extracted_facts stays for backward compat as a latest-call snapshot.

**Implementation chunks:**
1. Summarizer extension — write list-type facts as namespaced LeadProfileFact rows
2. Profile query service — new functions in leads/service.py
3. Memory.py upgrade — read from LeadProfileFact instead of extracted_facts JSON
4. New agent tools — get_lead_profile, get_lead_history, get_lead_pain_points
5. API enrichment — lead detail returns accumulated profile

## Risks

- **Namespace collision**: Need consistent `profile:`, `pain:`, `signal:` prefixes — documented and enforced
- **Deduplication across calls**: Normalize + case-insensitive check before inserting list-type facts
- **Performance**: Extra DB queries per memory.py call — mitigated by composite index
- **Prompt token budget**: Accumulated profile could grow large — need truncation strategy
- **Backward compatibility**: Lead.extracted_facts readers still work but won't see accumulated data

## Ready for Proposal

Yes — codebase is well-structured. Dual-write pattern from #34 provides foundation. No blockers found. Proceed to sdd-propose with Approach 1.
