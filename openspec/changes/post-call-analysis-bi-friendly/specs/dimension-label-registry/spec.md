# dimension-label-registry Specification

## Purpose

Define the contract between stable English backend dimension/category codes and client-language display labels. Analytics codes MUST never be localized. Display labels are resolved at render time from a registry keyed by code and client language.

## Requirements

### Requirement: Backend Codes Are Stable English Identifiers

All dimension/category codes stored in the database and used in analytics queries MUST be stable English identifiers (e.g. `current_provider`, `price`, `service_quality`, `COMPARANDO_OPCIONES`).

Backend codes MUST NOT change based on client language, client configuration, or locale settings.

#### Scenario: Spanish-language client — codes remain English

- GIVEN a client is configured with `language: "es"`
- WHEN a call analysis is run and stored
- THEN all stored codes (`primary_objection_category`, `pain_points[].category`, etc.) are English identifiers
- AND no Spanish translation is stored in analytics columns

#### Scenario: BI GROUP BY query is stable across clients

- GIVEN multiple clients with different languages (es, en)
- WHEN a BI query runs `SELECT primary_objection_category, COUNT(*) FROM call_analyses GROUP BY primary_objection_category`
- THEN all clients' data is grouped under the same English codes
- AND no duplicate buckets exist due to localization differences (e.g. "price" vs "precio")

---

### Requirement: Display Labels Resolved from Client-Language Registry

A label registry MUST map each backend code to a display label per supported client language.

The registry MUST be read-only configuration (not hardcoded in application logic). Label changes MUST NOT require a backend deployment.

The registry MUST support at minimum `es` (Spanish) and `en` (English) as target languages.

Example mapping:

| Code | ES label | EN label |
|------|----------|----------|
| `active_comparison` | Comparando opciones | Actively comparing |
| `current_provider` | Proveedor actual como traba | Resistance from current provider |
| `price` | Precio | Price |

#### Scenario: Spanish client sees Spanish display labels

- GIVEN a client configured with `language: "es"`
- WHEN the dashboard renders an objection category
- THEN the display label shown is the Spanish label from the registry (e.g. "Proveedor actual como traba")
- AND the underlying stored code remains `current_provider`

#### Scenario: English client sees English display labels

- GIVEN a client configured with `language: "en"`
- WHEN the dashboard renders the same objection category
- THEN the display label shown is the English label (e.g. "Resistance from current provider")
- AND the stored code is unchanged

#### Scenario: Missing label falls back to code

- GIVEN a code exists in the analytics database but has no label entry in the registry for the client's language
- WHEN the UI renders
- THEN the backend code is displayed as-is (e.g. `current_provider`)
- AND no error is thrown

---

### Requirement: Label Changes Do Not Require Backend Deploy

The label registry MUST be stored in configuration (file, table, or external config), not in compiled application code.

A label change (adding a language, updating a translation) MUST be deployable independently of backend code changes.

#### Scenario: New language added without backend deploy

- GIVEN the registry currently supports `es` and `en`
- WHEN a new client language `pt` (Portuguese) needs to be supported
- THEN a new entry is added to the registry config
- AND no backend code change is required
- AND the new labels are served at render time

#### Scenario: Label text updated — no analytics impact

- GIVEN the display label for `price` in `es` is updated from "Precio" to "Costo del seguro"
- WHEN the change is deployed
- THEN the stored `price` code in the database is unchanged
- AND all historical queries and BI exports are unaffected
- AND the updated label is shown in the UI immediately

---

### Requirement: Analytics Queries Never Use Display Labels

Analytics exports, BI query results, and API responses used for reporting MUST use backend codes, not display labels.

Display labels are a UI-only concern. They MUST NOT leak into analytics responses, CSV exports, or API endpoints consumed by BI tools.

#### Scenario: BI export contains codes, not labels

- GIVEN a client requests a CSV export of call analysis data
- WHEN the export is generated
- THEN all category columns contain English codes (e.g. `current_provider`, `price`)
- AND no localized display labels are included in the export

#### Scenario: Analytics API returns codes

- GIVEN a BI tool queries the analytics API for objection breakdown
- WHEN the response is returned
- THEN category values in the JSON response are English codes
- AND the BI tool applies its own label mapping if display labels are needed
