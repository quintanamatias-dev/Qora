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

- [ ] The page uses a 5-column grid: **Transcript** on the left (2/5),
      **Analysis** on the right (3/5). Analysis is the wider region.
- [ ] The transcript is **sticky** — scrolling the analysis cards keeps the
      transcript in view instead of leaving a large empty gray area below it.
- [ ] Analysis dimension cards **flow through balanced columns** (masonry):
      1 column on small screens, 2 on `lg`, 3 on `2xl`. Short cards (e.g. empty
      "Notes") do not leave tall gaps next to a long "Objections" card.

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
      correction rows, masonry `dimension-grid` columns.
- [ ] `call-detail-page.test.tsx` — analysis region is wider
      (`lg:col-span-3`) than transcript (`lg:col-span-2`) and transcript is
      `lg:sticky`.

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
