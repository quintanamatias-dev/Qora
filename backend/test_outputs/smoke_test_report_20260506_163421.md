# Smoke Test Report — Universal Analysis Pipeline

**Date**: 2026-05-06 16:34 ART  
**Result**: 24/24 checks passed  
**Total GPT calls**: 22 (11 per scenario)  
**Total GPT time**: ~97s  

---

## Scenario 1: POSITIVE — Complete call, high interest

### Transcript

> **Agente**: Hola, buenas tardes. Habla Jaumpablo de Quintana Seguros. Hablo con Martín Rodríguez?  
> **Lead**: Sí, sí, hola. Qué tal?  
> **Agente**: Cómo estás, Martín? Te llamaba porque vimos que habías consultado por un seguro de auto. Tenés un minutito?  
> **Lead**: Sí, dale. Justamente estoy necesitando porque se me vence el seguro el mes que viene y me aumentaron un cuarenta por ciento. Es una locura lo que me están cobrando.  
> **Agente**: Te entiendo perfectamente. Es una queja muy común últimamente. Con qué compañía estás actualmente?  
> **Lead**: Estoy con La Caja. Mirá, no me quejo del servicio en general, pero cuando tuve un siniestro el año pasado tardaron tres meses en resolver el reclamo. Tres meses sin respuesta. Llamaba y nadie me atendía. Un desastre.  
> **Agente**: Uy, lamento escuchar eso. Nosotros tenemos un compromiso de resolución de siniestros en 72 horas hábiles. Qué auto tenés?  
> **Lead**: Tengo un Toyota Corolla 2022. Ah no, perdón, en realidad es un 2023. Me confundí. El modelo es un Corolla Cross, no Corolla a secas.  
> **Agente**: Perfecto, Toyota Corolla Cross 2023. Querés un seguro todo riesgo o terceros completo?  
> **Lead**: Mirá, la verdad que me interesa todo riesgo para el auto, y también quería consultar por un seguro de hogar. Tenemos un departamento y no tenemos nada. Mi esposa me viene diciendo hace meses que tenemos que asegurar los contenidos.  
> **Agente**: Excelente. El auto todo riesgo y hogar. Tienen algún requisito particular? Buscan algo con franquicia baja, buen precio...?  
> **Lead**: Principalmente precio competitivo pero con buena cobertura. Con La Caja pagaba mucho por poca cobertura. Y si puede ser con menor franquicia, mejor.  
> **Agente**: Perfecto. Mirá, te armo una cotización para ambos. El todo riesgo del Corolla Cross 2023 y el seguro de hogar con cobertura de contenidos.  
> **Lead**: Dale, genial. Me la podés mandar mañana? Porque hoy estoy medio complicado, trabajo en la municipalidad y tengo reuniones hasta las seis.  
> **Agente**: Sin problema, mañana a primera hora te la mando por WhatsApp. Este es tu número de WhatsApp?  
> **Lead**: Sí, este mismo. Ah, y mi mail es martinrodriguez@gmail.com por si necesitás mandarme algo por escrito. Yo soy de consultar las cosas con mi señora antes de decidir, así que si me mandás algo detallado mejor.  
> **Agente**: Perfecto Martín, te mando todo detallado mañana. Algo más que quieras consultar?  
> **Lead**: No, por ahora está bien. Ah sí, una cosa: es muy caro? Porque mi cuñado me dijo que los seguros todo riesgo están carísimos este año.  
> **Agente**: Mirá, depende mucho del auto y la zona, pero te hago el mejor precio posible. Somos bastante competitivos en Corolla Cross. Mañana cuando veas la cotización me decís qué te parece.  
> **Lead**: Dale, perfecto. Muchas gracias Jaumpablo.  
> **Agente**: Gracias a vos Martín, te mando todo mañana. Que tengas buena tarde!  
> **Lead**: Igualmente, chau.

### Simulated Lead Context (injected)

```json
{
  "name": "Martín Rodríguez",
  "phone": "+5491155551234",
  "car_make": "Toyota",
  "car_model": "Corolla",       // <-- deliberadamente MAL (debería ser Corolla Cross)
  "car_year": 2022,              // <-- deliberadamente MAL (debería ser 2023)
  "current_insurance": "La Caja"
}
```

---

### 1. Summary ✅

| | |
|---|---|
| **Prompt** | `Describe in one sentence what happened during the call. Write the response in Spanish. Third person, factual, descriptive — no opinions, no analysis, no scoring. Return JSON with: text (max 40 tokens).` |
| **Duration** | 2697ms |

**Response:**

> Durante la llamada, el agente de Quintana Seguros contactó a Martín Rodríguez para ofrecerle una cotización de un seguro de auto y de hogar, tras quejarse Rodríguez de su actual compañía.

---

### 2. Objections ✅

| | |
|---|---|
| **Prompt** | Expert at detecting objections and pushback. Categories: price, current_provider, timing, authority, trust, need, information_gap, coverage_or_product_fit, payment_or_budget, documentation_or_data, channel_preference, bad_experience, hard_rejection, other. Max 5 objections. |
| **Duration** | 14744ms |

**Response — 5 objections detected:**

| # | Category | Strength | Resolution | Evidence |
|---|----------|----------|------------|----------|
| 1 | **price** | high | partially_resolved | _"mi cuñado me dijo que los seguros todo riesgo están carísimos este año"_ |
| 2 | current_provider | medium | unresolved | _"cuando tuve un siniestro... tardaron tres meses... Un desastre"_ |
| 3 | timing | medium | resolved | _"hoy estoy medio complicado, trabajo en la municipalidad"_ |
| 4 | need | medium | resolved | _"mi esposa me viene diciendo hace meses que tenemos que asegurar"_ |
| 5 | coverage_or_product_fit | medium | resolved | _"Con La Caja pagaba mucho por poca cobertura"_ |

Primary: **price** (is_primary=true)

---

### 3. Call Outcome ✅

| | |
|---|---|
| **Prompt** | Classify outcome (11 categories) + abandonment analysis (was_abrupt, abandonment_trigger). |
| **Duration** | 4328ms |

**Response:**

| Field | Value |
|-------|-------|
| classification | **completed_positive** |
| reason | Lead expressed clear interest in obtaining insurance quotes for both a car and home policy |
| confidence | high |
| was_abrupt | null |
| abandonment_trigger | null |

---

### 4. Identified Problem ✅

| | |
|---|---|
| **Prompt** | Expert at detecting pain points. Categories: cost, coverage, renewal, bad_experience, lack_of_clarity, new_need, risk_exposure, comparison, deadline, dissatisfaction, other. Boundary rules to avoid cross-dimension overlap. |
| **Duration** | 8697ms |

**Response — 5 pain points:**

| # | Category | Urgency | Evidence | Primary |
|---|----------|---------|----------|---------|
| 1 | **renewal** | high | _"se me vence el seguro el mes que viene"_ | **yes** |
| 2 | cost | medium | _"me aumentaron un 40%... Es una locura"_ | no |
| 3 | bad_experience | medium | _"tardaron tres meses en resolver el reclamo... Un desastre"_ | no |
| 4 | new_need | medium | _"quería consultar por un seguro de hogar... no tenemos nada"_ | no |
| 5 | coverage | medium | _"con La Caja pagaba mucho por poca cobertura"_ | no |

---

### 5. Service Issues ✅

| | |
|---|---|
| **Prompt** | Expert at detecting service complaints. Source: current_provider, previous_provider, our_company, unknown. |
| **Duration** | 3906ms |

**Response — 2 issues:**

| # | Category | Source | Severity | Evidence |
|---|----------|--------|----------|----------|
| 1 | **delay** | **current_provider** | high | _"tardaron tres meses en resolver el reclamo"_ |
| 2 | communication_problem | **current_provider** | medium | _"Llamaba y nadie me atendía"_ |

> **Note**: Both correctly attributed to `current_provider` (La Caja), not `our_company`. This is an opportunity signal for us, not a problem with our service.

---

### 6. Commitments ✅

| | |
|---|---|
| **Prompt** | Expert at detecting concrete commitments. Types: send_document, receive_quote, review_proposal, consult_third_party, callback, continue_by_channel, compare_options, other. |
| **Duration** | 6310ms |

**Response — 3 commitments:**

| # | Type | Owner | Due | Strength | Evidence |
|---|------|-------|-----|----------|----------|
| 1 | **receive_quote** | agent | tomorrow | **strong** | _"Mañana a primera hora te la mando por WhatsApp"_ |
| 2 | send_document | agent | tomorrow | strong | _"Te mando todo detallado mañana"_ |
| 3 | consult_third_party | lead | unknown | medium | _"Yo soy de consultar las cosas con mi señora antes de decidir"_ |

---

### 7. Detected Interests ✅

| | |
|---|---|
| **Prompt** | Expert at detecting insurance product interests. Valid products: auto_todo_riesgo, auto_terceros_completo, auto_terceros, moto, hogar, vida, comercio, art, caucion. Valid need tags: precio_competitivo, mayor_cobertura, menor_franquicia, atencion_personalizada, rapidez, financiacion, comparar_con_actual, renovacion_proxima. |
| **Duration** | 3369ms |

**Response — 2 products detected:**

| # | Product | Needs | Evidence | Confidence |
|---|---------|-------|----------|------------|
| 1 | **auto_todo_riesgo** | precio_competitivo, menor_franquicia, mayor_cobertura | _"me interesa todo riesgo para el auto"_ | high |
| 2 | **hogar** | precio_competitivo, mayor_cobertura | _"quería consultar por un seguro de hogar"_ | high |

---

### 8. Interest Level ✅

| | |
|---|---|
| **Prompt** | Score interest 0-100. Injected: detected products from Agent 1 (auto_todo_riesgo + hogar). Formula: `max(product_scores) * 0.7 + previous * 0.3` (no previous → 100% current). |
| **Duration** | 3185ms |

**Response:**

| Field | Value |
|-------|-------|
| general_score | **80** (high) |
| level | high |
| per_product | auto_todo_riesgo: 80, hogar: 80 |
| positive_signals | Explicitly stated interest in both products, Discussed specifics like deductibles, Requested a quote for next day |
| negative_signals | Mentioned hearing insurance is expensive |
| confidence | high |

---

### 9. Profile Facts ✅

| | |
|---|---|
| **Prompt** | Expert at building persistent personality profile. Operations: add/update/remove. 11 categories. Boundary rules: NOT temporal context (those → misc_notes). Injected: `CURRENT FACTS: []` (first call). |
| **Duration** | 7356ms |

**Response — 5 facts added:**

| # | Category | Fact | Evidence |
|---|----------|------|----------|
| 1 | provider_relationship | Negative experience with La Caja (slow claims) | _"tardaron tres meses en resolver el reclamo"_ |
| 2 | **decision_style** | Consults with his wife before deciding | _"yo soy de consultar las cosas con mi señora"_ |
| 3 | **occupation** | Works at the municipality | _"trabajo en la municipalidad"_ |
| 4 | lifestyle | Interested in insuring apartment contents | _"no tenemos nada... asegurar los contenidos"_ |
| 5 | financial_attitude | Seeks competitive pricing with good coverage | _"precio competitivo pero con buena cobertura"_ |

---

### 10. Misc Notes ✅

| | |
|---|---|
| **Prompt** | Operational notes (temporal/operational context, NOT stable traits). Types: continuity, pending_topic, tone_context, temporary_context, caution, other. Max 5 (prefer 3). Injected: `CURRENT NOTES: []` (first call). |
| **Duration** | 4228ms |

**Response — 3 notes:**

| # | Type | Note |
|---|------|------|
| 1 | temporary_context | Lead's current auto insurance expires next month |
| 2 | pending_topic | Lead requested a quote for auto and home insurance to be sent tomorrow |
| 3 | continuity | Lead prefers competitive pricing with good coverage and low deductible |

---

### 11. Data Corrections ✅

| | |
|---|---|
| **Prompt** | Expert at detecting personal data corrections. Supported fields: age, car_make, car_model, car_year, current_insurance, email, name, phone. Injected lead snapshot with deliberate errors (car_model=Corolla, car_year=2022). |
| **Duration** | 5303ms |

**Response — 3 corrections detected:**

| # | Field | Current | Corrected | Confidence | Evidence | Applied |
|---|-------|---------|-----------|------------|----------|---------|
| 1 | **car_year** | 2022 | **2023** | 1.0 | _"Ah no, perdón, en realidad es un 2023"_ | **yes** |
| 2 | **car_model** | Corolla | **Corolla Cross** | 1.0 | _"el modelo es un Corolla Cross, no Corolla a secas"_ | **yes** |
| 3 | **email** | null | martinrodriguez@gmail.com | 1.0 | _"mi mail es martinrodriguez@gmail.com"_ | **yes** |

---

### 12. Next Action (Post-Analysis Engine) ✅

| | |
|---|---|
| **Input** | Structured context from all dimensions (NOT transcript). outcome=completed_positive, interest=80, commitments=[receive_quote/strong], objections=[price/high], lead={call_count:1, do_not_call:false}, client={max_attempts:5, min_interest:40} |
| **Decision** | **Rules engine** (no GPT needed) |

**Response:**

| Field | Value |
|-------|-------|
| action | **follow_up** |
| reason | Lead committed to receiving a quote (strength=strong) |
| confidence | high |
| decided_by | **rules** (P3 — commitment-based) |
| next_action_at | null |
| priority | normal |

> **Decision path**: P1 (hard stops) → skip. P2 (max attempts) → skip (1 < 5). P3 (commitments) → **MATCH**: receive_quote with strength=strong → `follow_up`.

---
---

## Scenario 2: NEGATIVE — Hostile rejection

### Transcript

> **Agente**: Hola, buenas tardes. Habla Jaumpablo de Quintana Seguros. Hablo con Ricardo Gómez?  
> **Lead**: Sí, qué querés?  
> **Agente**: Cómo estás Ricardo? Te llamaba porque consultaste por...  
> **Lead**: Pará, pará. Yo no consulté nada. Me están llamando todo el día de distintas empresas, me tienen harto.  
> **Agente**: Disculpá Ricardo, tenemos tu contacto de una consulta web. Solo quería ofrecerte...  
> **Lead**: No me interesa. Ya tengo seguro y no quiero cambiar. Estoy bien con el que tengo.  
> **Agente**: Entiendo perfectamente. Puedo preguntarte con quién estás actualmente? Capaz te podemos ofrecer algo mejor...  
> **Lead**: Estoy con Federación Patronal y estoy perfecto. No necesito nada. Aparte los seguros están todos caros, es un robo lo que cobran. No me interesa pagar más de lo que ya pago.  
> **Agente**: Te entiendo. Mirá, nosotros muchas veces logramos precios más competitivos que...  
> **Lead**: Mirá hermano, te lo digo bien: no me llamen más. No me interesa, no quiero que me llamen nunca más. Si me vuelven a llamar me voy a quejar. Quedó claro?  
> **Agente**: Sí, perfectamente Ricardo. Te sacamos de la lista de contacto. Disculpá la molestia.  
> **Lead**: Bien. Chau.

---

### 1. Summary ✅

| | |
|---|---|
| **Duration** | 1246ms |

**Response:**

> El agente de seguros llamó a Ricardo Gómez, quien se mostró muy molesto por las constantes llamadas y rechazó cualquier oferta, pidiendo que no lo contacten más.

---

### 2. Objections ✅

| | |
|---|---|
| **Duration** | 6434ms |

**Response — 3 objections:**

| # | Category | Strength | Resolution | Evidence |
|---|----------|----------|------------|----------|
| 1 | **current_provider** | high | unresolved | _"Ya tengo seguro y no quiero cambiar"_ |
| 2 | price | high | unresolved | _"los seguros están todos caros, es un robo"_ |
| 3 | **hard_rejection** | high | unresolved | _"no me llamen más... no quiero que me llamen nunca más"_ |

---

### 3. Call Outcome ✅

| | |
|---|---|
| **Duration** | 1495ms |

**Response:**

| Field | Value |
|-------|-------|
| classification | **do_not_contact** |
| reason | Lead explicitly requested to not be contacted again |
| confidence | high |
| was_abrupt | null (completed set → nullified by validator) |
| abandonment_trigger | null |

---

### 4. Identified Problem ✅

| | |
|---|---|
| **Duration** | 3826ms |

**Response — 3 pain points:**

| # | Category | Urgency | Evidence |
|---|----------|---------|----------|
| 1 | cost | medium | _"los seguros están todos caros, es un robo"_ |
| 2 | dissatisfaction | high | _"Me están llamando todo el día... me tienen harto"_ |
| 3 | comparison | low | _"Ya tengo seguro y no quiero cambiar"_ |

---

### 5. Service Issues ✅

| | |
|---|---|
| **Duration** | 5303ms |

**Response — 4 issues:**

| # | Category | Source | Severity | Evidence |
|---|----------|--------|----------|----------|
| 1 | communication_problem | unknown | high | _"Me están llamando todo el día"_ |
| 2 | bad_experience | unknown | high | _"no me llamen más"_ |
| 3 | poor_attention | **our_company** | medium | _"tenemos tu contacto de una consulta web"_ |
| 4 | claim_problem | current_provider | medium | _"es un robo lo que cobran"_ |

> **Note**: Issue #3 correctly detected as `our_company` — our agent claimed a web consultation the lead denies making.

---

### 6. Commitments ✅

| | |
|---|---|
| **Duration** | 2224ms |

**Response:** Empty array `[]` — no commitments (correct for hostile rejection).

---

### 7. Detected Interests ✅

| | |
|---|---|
| **Duration** | 997ms |

**Response:** Empty array `[]` — no product interest (correct).

---

### 8. Interest Level ✅

| | |
|---|---|
| **Duration** | 2247ms |

**Response:**

| Field | Value |
|-------|-------|
| general_score | **0** (very_low) |
| level | very_low |
| per_product | [] (no products) |
| positive_signals | [] |
| negative_signals | Contacted too often, Satisfied with current provider, Strong refusal to engage |
| confidence | high |

---

### 9. Profile Facts ✅

| | |
|---|---|
| **Duration** | 3653ms |

**Response — 4 facts:**

| # | Category | Fact |
|---|----------|------|
| 1 | provider_relationship | Currently with Federación Patronal and satisfied |
| 2 | financial_attitude | Feels insurance prices are too high ("robbery") |
| 3 | decision_style | Decisive, doesn't want to change provider |
| 4 | communication_preference | Does not want to be contacted again |

---

### 10. Misc Notes ✅

| | |
|---|---|
| **Duration** | 4214ms |

**Response — 3 notes:**

| # | Type | Note |
|---|------|------|
| 1 | **caution** | Lead is highly irritable and does not want further calls |
| 2 | tone_context | Lead expressed annoyance and frustration |
| 3 | temporary_context | Currently insured with Federación Patronal, satisfied |

---

### 11. Data Corrections ✅

| | |
|---|---|
| **Duration** | 1200ms |

**Response:** Empty array `[]` — no corrections (correct, no personal data discussed).

---

### 12. Next Action ✅

| | |
|---|---|
| **Input** | outcome=do_not_contact, interest=0, commitments=[], objections=[current_provider, price, hard_rejection], lead={call_count:1, do_not_call:false}, client={max_attempts:5, close_on_hard_rejection:true} |
| **Decision** | **Rules engine** (no GPT needed) |

**Response:**

| Field | Value |
|-------|-------|
| action | **close_lead** |
| reason | Hard stop: outcome classification is 'do_not_contact' |
| confidence | high |
| decided_by | **rules** (P1 — hard stops) |

> **Decision path**: P1 (hard stops) → **MATCH**: outcome=do_not_contact ∈ {do_not_contact, wrong_number, hostile} → `close_lead`. No further rules evaluated.

---
---

## Timing Summary

### Scenario 1 (Positive) — 11 calls, ~14.7s total

| Dimension | Duration |
|-----------|----------|
| Summary | 2697ms |
| Interests (Agent 1) | 3369ms |
| Interest Level (Agent 2) | 3185ms |
| Objections | 14744ms |
| Outcome | 4328ms |
| Problem | 8697ms |
| Service Issues | 3906ms |
| Commitments | 6310ms |
| Profile Facts | 7356ms |
| Misc Notes | 4228ms |
| Data Corrections | 5303ms |

> Note: Dimensions 1-10 run in parallel. next_action runs sequentially after (rules only, no GPT call needed).

### Scenario 2 (Negative) — 11 calls, ~6.4s total

| Dimension | Duration |
|-----------|----------|
| Summary | 1246ms |
| Interests (Agent 1) | 997ms |
| Interest Level (Agent 2) | 2247ms |
| Objections | 6434ms |
| Outcome | 1495ms |
| Problem | 3826ms |
| Service Issues | 5303ms |
| Commitments | 2224ms |
| Profile Facts | 3653ms |
| Misc Notes | 4214ms |
| Data Corrections | 1200ms |

> Shorter transcript = faster responses across the board.
