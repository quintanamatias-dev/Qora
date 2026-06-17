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
