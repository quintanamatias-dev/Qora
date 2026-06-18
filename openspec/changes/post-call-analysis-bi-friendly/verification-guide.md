# Verification Guide — post-call-analysis-bi-friendly

Developer-facing checklist for verifying the BI-friendly post-call analysis
changes. Split into **visible dashboard checks** (what a reviewer can see in the
UI) and **technical / DB checks** (what proves the pipeline actually persists
the normalized data). Read the **Stale analysis caveat** before judging an
existing call's analysis content.

---

## 1. Visible dashboard checks (Call Detail page)

Route: `/app/:clientId/calls/:sessionId`

### Layout

- [ ] The Transcript and ALL analysis sections live in **ONE shared responsive
      masonry flow** (CSS columns): 1 column on small screens, 2 on `lg`, 3 on
      `2xl`, with `[column-fill:balance]`. There is **no** separate floated
      transcript region and **no** separate analysis region — it is a single
      card flow.
- [ ] The **Transcript is the first card** in that flow, so it lands **top-left**.
      Because it shares the same columns as the analysis cards, short analysis
      cards (Profile Facts, Notes, Data Corrections, …) **fill the empty space
      BELOW the transcript** in the left column — analysis is NOT confined to the
      right side.
- [ ] The transcript is **NOT sticky / fixed** and **NOT a floated aside** — there
      is no frozen or pinned left column. Scrolling the page scrolls the
      transcript away with everything else. (The transcript may still scroll
      **internally** via its own `max-height` + `overflow-y-auto` for very long
      transcripts, but it is never pinned.)
- [ ] Each card (transcript included) uses `break-inside-avoid` so it never
      splits across a column boundary. Short cards (e.g. empty "Notes") do not
      leave tall gaps next to a long "Objections" card; they flow into the
      nearest open space, including under the transcript.

### Data Corrections section

- [ ] Each correction renders as a light inline row: `field → corrected_value`
      (e.g. `car_make → Volkswagen`), with the old value struck through when
      present. No per-row gray card, no per-row sync badge, no confidence %.
- [ ] The section header shows exactly two **minimal** badges: **`Qora`** and
      **`CRM`**. They are single words — NOT verbose pills like
      `Qora applied ✓` / `CRM unknown`.
- [ ] Badge **colour** carries the state (hover for the full wording via the
      `title` attribute / `data-state`):
  - **Qora**: green = all applied, red = partial, gray = pending.
  - **CRM**: green = all `in_sync`, red = any `out_of_sync`,
    gray = unknown / null / stale / no integration.
- [ ] **Honesty check**: if the corrections carry no real CRM sync status
      (null / `stale` / `unknown`), the CRM badge is **gray**, never green.
      No fake "synced" claim.

### Other dimensions

- [ ] Objections, Pain Points, Service Issues show **structured fields**
      (category / strength / severity / source) plus inline evidence quotes —
      not prose-only summaries.
- [ ] Detected Interests show normalized value codes tagged `product` / `need`.
- [ ] "BI Summary" row (when present) shows primary objection/pain categories
      and counts from the denormalized columns.

---

## 2. Technical / DB checks

These prove the pipeline normalizes and persists BI data, independent of the UI.

### Frontend gate

```bash
cd frontend
npx vitest run src/features/calls/call-analysis-panel.test.tsx \
               src/features/calls/call-detail-page.test.tsx
npx tsc --noEmit
```

- [ ] `call-analysis-panel.test.tsx` — structured dimension rendering, minimal
      `Qora`/`CRM` badges (asserted via `data-state` + colour class), inline
      correction rows, and (via the standalone `CallAnalysisPanel` wrapper) the
      masonry `dimension-grid` columns.
- [ ] `call-detail-page.test.tsx` — transcript is **NOT** `sticky`/`fixed` and
      **NOT** a separate floated aside (`float-*` / `w-2/5` absent); the
      transcript is a `break-inside-avoid` card and is a **direct child of the
      shared `call-detail-content` flow** alongside the analysis cards; that
      content wrapper is the unified `columns-1 lg:columns-2 2xl:columns-3`
      masonry (no `flow-root` float-containment wrapper).

### Backend / DB

The normalized analysis lives in the `call_analyses` table. The pipeline entry
point is `app/summarizer.generate_summary_and_facts(session_id, db)`, invoked
post-call from `app/calls/service.py`. It **upserts** the row
(`_upsert_call_analysis`).

- [ ] BI denormalized columns exist and are backfilled
      (`backend/scripts/migrate_bi_columns.py`): `primary_objection_category`,
      `primary_pain_category`, `objections_count`, `pain_points_count`,
      `service_issues_count`.
- [ ] Inspect a row:

  ```sql
  SELECT classification,
         primary_objection_category, primary_pain_category,
         objections_count, pain_points_count, service_issues_count,
         analysis_status, analyzed_at
  FROM call_analyses
  WHERE session_id = '<session-id>';
  ```

- [ ] `data_corrections` JSON carries `field`, `corrected_value`/`old_value`,
      `applied` (per-call) or `applied_to_qora` (analytics), and
      `crm_sync_status`. The UI derives the section badges from these — verify
      the colours match the stored values.
- [ ] Relevant backend suites pass (analysis + corrections):

  ```bash
  cd backend
  pytest tests/test_summarizer_corrections.py \
         tests/unit/analysis/test_data_corrections_custom_fields.py
  ```

---

## 3. Stale analysis caveat (IMPORTANT — read before judging content)

The analysis stored in `call_analyses` is a **snapshot from the moment the call
was analyzed**. It is NOT recomputed when the analysis pipeline changes.

> **Known stale row:** the `new_need` pain point on **Mora's existing call** was
> generated **before** these pipeline changes. It will remain in the persisted
> `call_analyses` row until that call is **re-analyzed** or the row is manually
> corrected / backfilled. The UI shows the persisted data **honestly** — it does
> NOT silently pretend the value changed to match the new pipeline.

So if you open Mora's call and still see `new_need`, that is **expected** and is
not a UI bug. To make it reflect the new pipeline, the row must be re-analyzed.

### Re-analyzing / backfilling a call

There is currently **no dedicated per-call "re-analyze" endpoint or CLI**.
Re-analysis means re-invoking the summarizer for the session, which upserts
(overwrites) the existing `call_analyses` row:

```python
from app.summarizer import generate_summary_and_facts
# inside an async DB session:
await generate_summary_and_facts(session_id, db)
await db.commit()
```

`backend/scripts/seed_analysis_demo_call.py` demonstrates this exact production
persistence path for a seeded call.

**Gap to close (follow-up):** a proper replay/backfill tool is needed — e.g. a
script or admin action that takes one or more `session_id`s, re-runs
`generate_summary_and_facts`, and reports which rows were updated. Until that
exists, stale rows like Mora's `new_need` must be re-analyzed manually with the
snippet above. Do not patch the value directly in the UI layer — keep the UI an
honest mirror of persisted data.

---

## 4. Future taxonomy refinements (NOT implemented yet — design notes only)

These are deliberately **out of scope** for the current change. They are recorded
here so a future change can pick them up; do **not** implement them as part of the
layout/UI work.

### 4.1 `lack_of_clarity` vs `information_gap` distinction

The current taxonomy blurs these. A future refinement should split the concept by
**where the signal sits in the funnel**:

- **pain** — when the signal is user **frustration** (the user is bothered /
  struggling). Example surface: Pain Points.
- **objection** — when the signal is a **sales blocker / traba** (it actively
  stops the deal from advancing). Example surface: Objections.
- **issue** — when the signal is a **product/service information problem**
  (missing or wrong info about the product/service). Example surface: Service
  Issues.

So a single "lack of clarity" today may map to a pain, an objection, or an issue
depending on intent. `information_gap` should be reserved for the **issue**
(product/service information problem) reading, and `lack_of_clarity` re-scoped (or
removed) so the three surfaces stop overlapping. Needs a migration + backfill plan
for existing `call_analyses` rows before changing the prompts/normalizer.

### 4.2 Split "Interests" into cross-sell vs product-strategy/need

The Detected Interests dimension currently merges everything into `product` /
`need` source tags. A future refinement should distinguish:

- **cross-sell interests** — additional products the user could be sold.
- **product-strategy / need interests** — signals about what the user actually
  needs (feeds product strategy), not an immediate up/cross-sell.

This split should be **configurable per client** (different clients care about
different interest taxonomies), so it belongs with the per-client dimension/label
config rather than hard-coded. Until then, the UI keeps showing the honest flat
`product` / `need` tags.
