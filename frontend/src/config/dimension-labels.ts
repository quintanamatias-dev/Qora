/**
 * Dimension Label Registry — maps stable English backend codes to client-language
 * display labels.
 *
 * Design: AD-5 — TS const map, tree-shakeable, type-safe, frontend-only.
 * Analytics codes (keys) MUST remain stable English identifiers.
 * Display labels are a UI-only concern and MUST NOT leak into analytics responses.
 *
 * Spec: openspec/changes/post-call-analysis-bi-friendly/specs/dimension-label-registry/spec.md
 */

export type LabelLocale = 'es' | 'en'

/**
 * Registry of dimension/category codes → per-locale display labels.
 *
 * Keys are stable English identifiers matching backend codes stored in DB.
 * Values are locale maps with at minimum 'es' and 'en' entries.
 *
 * Adding a new locale or updating a label here requires no backend deploy.
 */
export const DIMENSION_LABELS: Record<string, Record<LabelLocale, string>> = {
  // ── Objection categories ──────────────────────────────────────────────────
  current_provider: {
    es: 'Proveedor actual como traba',
    en: 'Resistance from current provider',
  },
  price: {
    es: 'Precio',
    en: 'Price',
  },
  service_quality: {
    es: 'Calidad de servicio',
    en: 'Service quality',
  },
  coverage_gap: {
    es: 'Brecha de cobertura',
    en: 'Coverage gap',
  },
  timing: {
    es: 'Momento no adecuado',
    en: 'Bad timing',
  },
  trust: {
    es: 'Falta de confianza',
    en: 'Lack of trust',
  },
  need_to_think: {
    es: 'Necesita pensarlo',
    en: 'Needs to think it over',
  },
  // ── Pain point categories ─────────────────────────────────────────────────
  cost: {
    es: 'Costo',
    en: 'Cost',
  },
  coverage: {
    es: 'Cobertura',
    en: 'Coverage',
  },
  renewal: {
    es: 'Renovación',
    en: 'Renewal',
  },
  bad_experience: {
    es: 'Mala experiencia',
    en: 'Bad experience',
  },
  lack_of_clarity: {
    es: 'Falta de claridad',
    en: 'Lack of clarity',
  },
  new_need: {
    es: 'Nueva necesidad',
    en: 'New need',
  },
  risk_exposure: {
    es: 'Exposición al riesgo',
    en: 'Risk exposure',
  },
  deadline: {
    es: 'Plazo / Urgencia',
    en: 'Deadline / Urgency',
  },
  dissatisfaction: {
    es: 'Insatisfacción',
    en: 'Dissatisfaction',
  },
  // ── Interest / signal tags ────────────────────────────────────────────────
  active_comparison: {
    es: 'Comparando opciones',
    en: 'Actively comparing',
  },
  competitive_pain: {
    es: 'Dolor con proveedor actual',
    en: 'Pain with current provider',
  },
  urgency_signal: {
    es: 'Señal de urgencia',
    en: 'Urgency signal',
  },
  quote_request: {
    es: 'Solicitó cotización',
    en: 'Requested a quote',
  },
  // ── Shared / generic ─────────────────────────────────────────────────────
  other: {
    es: 'Otro',
    en: 'Other',
  },
  unknown: {
    es: 'Desconocido',
    en: 'Unknown',
  },
  // ── IssueCategoryType — service issue tags (cubora-accumulated-dimension-rankings)
  poor_attention: {
    es: 'Mala atención',
    en: 'Poor attention',
  },
  delay: {
    es: 'Demora',
    en: 'Delay',
  },
  lack_of_response: {
    es: 'Falta de respuesta',
    en: 'Lack of response',
  },
  claim_problem: {
    es: 'Problema con siniestro',
    en: 'Claim problem',
  },
  billing_issue: {
    es: 'Problema de facturación',
    en: 'Billing issue',
  },
  administrative_problem: {
    es: 'Problema administrativo',
    en: 'Administrative problem',
  },
  communication_problem: {
    es: 'Problema de comunicación',
    en: 'Communication problem',
  },
  // ── PRODUCT_CATALOG — insurance product IDs (cubora-accumulated-dimension-rankings)
  auto_todo_riesgo: {
    es: 'Auto todo riesgo',
    en: 'Comprehensive auto',
  },
  auto_terceros_completo: {
    es: 'Auto terceros completo',
    en: 'Auto third-party complete',
  },
  auto_terceros: {
    es: 'Auto terceros',
    en: 'Auto third-party',
  },
  moto: {
    es: 'Moto',
    en: 'Motorcycle',
  },
  hogar: {
    es: 'Hogar',
    en: 'Home',
  },
  vida: {
    es: 'Vida',
    en: 'Life',
  },
  comercio: {
    es: 'Comercio',
    en: 'Commercial',
  },
  art: {
    es: 'ART',
    en: 'Personal accident (ART)',
  },
  caucion: {
    es: 'Caución',
    en: 'Surety bond',
  },
  // ── NEED_TAGS — detected lead needs (cubora-accumulated-dimension-rankings)
  precio_competitivo: {
    es: 'Precio competitivo',
    en: 'Competitive price',
  },
  mayor_cobertura: {
    es: 'Mayor cobertura',
    en: 'More coverage',
  },
  menor_franquicia: {
    es: 'Menor franquicia',
    en: 'Lower deductible',
  },
  atencion_personalizada: {
    es: 'Atención personalizada',
    en: 'Personalized service',
  },
  rapidez: {
    es: 'Rapidez',
    en: 'Speed',
  },
  financiacion: {
    es: 'Financiación',
    en: 'Financing',
  },
  comparar_con_actual: {
    es: 'Comparar con actual',
    en: 'Compare with current',
  },
  renovacion_proxima: {
    es: 'Renovación próxima',
    en: 'Upcoming renewal',
  },
}

/**
 * Resolve a display label for a backend code and locale.
 *
 * Returns the registered label if found, or the raw code as fallback.
 * Never throws. Safe to call with unknown codes.
 *
 * @param code   - Stable English backend code (e.g. 'current_provider')
 * @param locale - Target locale ('es' | 'en')
 * @returns Display label string, or code as fallback
 */
export function resolveLabel(code: string, locale: LabelLocale): string {
  return DIMENSION_LABELS[code]?.[locale] ?? code
}
