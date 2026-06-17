# call-analysis-dimensions Specification

## Purpose

Define the behavioral contracts for objection detection, pain point classification, interests normalization, and category code quality. These contracts govern what the AI extracts and how it is classified — the rules that make BI aggregations reliable.

## Requirements

### Requirement: Objection as Contextual Sales Blocker

An objection MUST be detected only when the lead uses a topic as an active reason to resist or slow down the sale — a "traba" (contextual sales blocker).

The `current_provider` category specifically MUST NOT fire on neutral mentions or purely informational references. It MUST fire when the lead expresses resistance framed around their current provider.

| Signal type | Example | Classification |
|-------------|---------|---------------|
| Contextual blocker | "recién cambié hace 6 meses, no vale la pena moverme" | `current_provider` objection |
| Neutral mention | "estoy con Sancor" | NOT an objection |
| Explicit rejection (strong) | "no me interesa cambiar para nada" | `current_provider` objection |

#### Scenario: Current provider as contextual blocker

- GIVEN a transcript where the lead says "recién cambié hace 6 meses, no me apuro"
- WHEN the objection detection pipeline runs
- THEN an objection with `category: "current_provider"` is produced
- AND `strength` reflects the friction level (e.g. `medium`)
- AND `resolution_status` is set appropriately

#### Scenario: Current provider as neutral mention — not an objection

- GIVEN a transcript where the lead says "actualmente estoy con Mercantil Andina"
- AND no resistance or reluctance is expressed
- WHEN the objection detection pipeline runs
- THEN NO objection entry with `category: "current_provider"` is produced

#### Scenario: Explicit rejection with current provider framing

- GIVEN a transcript where the lead says "X me cubre bien, no necesito moverme"
- WHEN the objection detection pipeline runs
- THEN a `current_provider` objection is produced with `strength: "high"`

---

### Requirement: Comparison Reclassified from Pain to Interest/Signal

`comparison` behavior (shopping around, requesting multiple quotes) MUST be classified as `interests` (a buying intent/action tag) and MUST NOT appear in `pain_points`.

The interests tag for comparison behavior MUST be `COMPARANDO_OPCIONES` (from the NEED_TAGS allowlist).

#### Scenario: Comparison behavior classified as interest

- GIVEN a transcript where the lead says "estoy comparando precios con varias aseguradoras"
- WHEN analysis runs
- THEN an interests entry with `tag: "COMPARANDO_OPCIONES"` is produced
- AND NO `pain_points` entry with a comparison-related category is produced

#### Scenario: Historical comparison category in pain_points

- GIVEN an existing call record has `comparison` in `pain_points` (pre-change data)
- WHEN BI queries run against that record
- THEN the old value is NOT modified or deleted
- AND a design/migration note documents that pre-change `comparison` in pain_points is stale

---

### Requirement: Interests Emit from NEED_TAGS Allowlist Only

The interests pipeline MUST emit tags exclusively from the `NEED_TAGS` allowlist. Free-form string generation that produces near-duplicate or arbitrary tags MUST be suppressed.

The allowlist MUST include at minimum: `COMPARANDO_OPCIONES` and other known recurring interest tags. An `other` fallback tag MUST be available for valid interests that do not match any specific allowlist entry.

#### Scenario: Known interest matches allowlist tag

- GIVEN a transcript where the lead says "estoy viendo varias opciones antes de decidir"
- WHEN interests analysis runs
- THEN `tag: "COMPARANDO_OPCIONES"` is emitted
- AND no free-form string like "comparando precios" or "buscando opciones" is emitted

#### Scenario: Unknown interest falls back to `other`

- GIVEN a transcript contains a genuine interest signal that matches no allowlist tag
- WHEN interests analysis runs
- THEN `tag: "other"` is emitted with the evidence quote preserved
- AND no arbitrary near-duplicate tag is invented

#### Scenario: Near-duplicate tags rejected

- GIVEN a previous analysis emitted "buscando alternativas" as an interests string
- WHEN the new pipeline runs on an equivalent transcript
- THEN a normalized allowlist tag is emitted instead
- AND "buscando alternativas" as a free-form string is NOT a valid output

---

### Requirement: Category Codes Pass Useful GROUP BY Test

Every category code used in `pain_points`, `objections`, `service_issues`, and `interests` MUST be specific enough that a BI analyst can write a useful `GROUP BY` query on it.

A code fails the test if it covers too many distinct root causes that a client would want to distinguish in separate buckets.

Failing codes MUST be split or renamed before Phase 2 ships. No vague code may be released as-is.

#### Scenario: Code passes GROUP BY test

- GIVEN category code `price` in `objections`
- WHEN a BI analyst runs `SELECT category, COUNT(*) FROM objections GROUP BY category`
- THEN the result is meaningful: all rows in this bucket share the same analytical root cause

#### Scenario: Vague code identified and split

- GIVEN category code `lack_of_clarity` covers "unclear pricing", "unclear coverage", and "unclear process"
- WHEN the code audit runs before Phase 2 ship
- THEN `lack_of_clarity` is replaced with specific codes (e.g. `unclear_pricing`, `unclear_coverage`, `unclear_process`)
- AND the old vague code is removed from the taxonomy

#### Scenario: `comparison` removed from pain_points taxonomy

- GIVEN the pain_points taxonomy currently includes `comparison` as a valid category
- WHEN this change ships
- THEN `comparison` MUST NOT be a valid `pain_points` category
- AND attempts to classify a pain point as `comparison` MUST default to another appropriate category or be routed to interests
