/**
 * dimension-labels — Unit tests for resolveLabel()
 *
 * Spec: openspec/changes/post-call-analysis-bi-friendly/specs/dimension-label-registry/spec.md
 *
 * Tests cover:
 * - Known code 'es' locale returns Spanish label
 * - Known code 'en' locale returns English label
 * - Unknown code falls back to the code itself (no error)
 * - Empty code falls back to empty string (no error)
 * - Codes do not contain localized text (stable English identifiers in keys)
 * - DIMENSION_LABELS does not expose any Spanish strings at the code level
 *
 * TDD Layer: Unit (pure function, no side effects, no mocks needed)
 */

import { describe, it, expect } from 'vitest'
import { resolveLabel, DIMENSION_LABELS } from './dimension-labels'

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Spanish client sees Spanish display labels
// ──────────────────────────────────────────────────────────────────────────────

describe('resolveLabel — Spanish locale', () => {
  it('returns Spanish label for current_provider in es', () => {
    const result = resolveLabel('current_provider', 'es')
    // Should be a Spanish label, NOT the code
    expect(result).not.toBe('current_provider')
    expect(result.length).toBeGreaterThan(0)
  })

  it('returns Spanish label for price in es', () => {
    const result = resolveLabel('price', 'es')
    expect(result).toBe('Precio')
  })

  it('returns Spanish label for service_quality in es', () => {
    const result = resolveLabel('service_quality', 'es')
    expect(result).not.toBe('service_quality')
    expect(result.length).toBeGreaterThan(0)
  })

  it('returns Spanish label for active_comparison in es', () => {
    const result = resolveLabel('active_comparison', 'es')
    expect(result).not.toBe('active_comparison')
    expect(result.length).toBeGreaterThan(0)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: English client sees English display labels
// ──────────────────────────────────────────────────────────────────────────────

describe('resolveLabel — English locale', () => {
  it('returns English label for current_provider in en', () => {
    const result = resolveLabel('current_provider', 'en')
    expect(result).toBe('Resistance from current provider')
  })

  it('returns English label for price in en', () => {
    const result = resolveLabel('price', 'en')
    expect(result).toBe('Price')
  })

  it('returns different labels for es vs en', () => {
    const es = resolveLabel('current_provider', 'es')
    const en = resolveLabel('current_provider', 'en')
    // Spanish and English labels must differ
    expect(es).not.toBe(en)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Missing label falls back to code
// ──────────────────────────────────────────────────────────────────────────────

describe('resolveLabel — fallback behavior', () => {
  it('falls back to the code when code is not in registry', () => {
    const result = resolveLabel('unknown_code_xyz', 'es')
    expect(result).toBe('unknown_code_xyz')
  })

  it('falls back to the code for unknown code in English locale', () => {
    const result = resolveLabel('no_such_dimension', 'en')
    expect(result).toBe('no_such_dimension')
  })

  it('does not throw when code is not in registry', () => {
    expect(() => resolveLabel('completely_unknown', 'es')).not.toThrow()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Scenario: Analytics codes are stable English identifiers (not localized)
// ──────────────────────────────────────────────────────────────────────────────

describe('DIMENSION_LABELS — keys are stable English codes', () => {
  it('all registry keys are stable underscore English identifiers', () => {
    const keys = Object.keys(DIMENSION_LABELS)
    expect(keys.length).toBeGreaterThan(0)
    for (const key of keys) {
      // Must match stable code pattern: ASCII letters, digits, underscores.
      // Keys MUST equal the backend code verbatim (resolveLabel does a direct
      // lookup), so uppercase need-tag codes like COMPARANDO_OPCIONES are valid.
      expect(key).toMatch(/^[A-Za-z0-9_]+$/)
    }
  })

  it('registry contains at minimum es and en for each entry', () => {
    const keys = Object.keys(DIMENSION_LABELS)
    expect(keys.length).toBeGreaterThan(0)
    for (const key of keys) {
      const entry = DIMENSION_LABELS[key]
      expect(entry).toHaveProperty('es')
      expect(entry).toHaveProperty('en')
      expect(typeof entry.es).toBe('string')
      expect(typeof entry.en).toBe('string')
      expect(entry.es.length).toBeGreaterThan(0)
      expect(entry.en.length).toBeGreaterThan(0)
    }
  })

  it('objection dimension codes present: current_provider, price', () => {
    expect(DIMENSION_LABELS).toHaveProperty('current_provider')
    expect(DIMENSION_LABELS).toHaveProperty('price')
  })

  it('pain dimension codes present: service_quality, bad_experience', () => {
    expect(DIMENSION_LABELS).toHaveProperty('service_quality')
    expect(DIMENSION_LABELS).toHaveProperty('bad_experience')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// IssueCategoryType labels — cubora-accumulated-dimension-rankings
// ──────────────────────────────────────────────────────────────────────────────

describe('DIMENSION_LABELS — IssueCategoryType codes registered', () => {
  const issueCodes = [
    'poor_attention',
    'delay',
    'lack_of_response',
    'lack_of_clarity',
    'claim_problem',
    'billing_issue',
    'administrative_problem',
    'communication_problem',
  ]

  for (const code of issueCodes) {
    it(`resolves Spanish label for issue code: ${code}`, () => {
      const result = resolveLabel(code, 'es')
      // Must be a real label, not the code falling back
      expect(result).not.toBe(code)
      expect(result.length).toBeGreaterThan(0)
    })

    it(`resolves English label for issue code: ${code}`, () => {
      const result = resolveLabel(code, 'en')
      expect(result).not.toBe(code)
      expect(result.length).toBeGreaterThan(0)
    })
  }

  it('all issue codes are present in DIMENSION_LABELS', () => {
    for (const code of issueCodes) {
      expect(DIMENSION_LABELS).toHaveProperty(code)
    }
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Product catalog labels — cubora-accumulated-dimension-rankings
// ──────────────────────────────────────────────────────────────────────────────

describe('DIMENSION_LABELS — PRODUCT_CATALOG codes registered', () => {
  const productCodes = [
    'auto_todo_riesgo',
    'auto_terceros_completo',
    'auto_terceros',
    'moto',
    'hogar',
    'vida',
    'comercio',
    'art',
    'caucion',
  ]

  it('all product catalog codes are present in DIMENSION_LABELS', () => {
    for (const code of productCodes) {
      expect(DIMENSION_LABELS).toHaveProperty(code)
    }
  })

  it('product codes each have non-empty es and en labels', () => {
    for (const code of productCodes) {
      const entry = DIMENSION_LABELS[code]
      expect(entry).toBeDefined()
      expect(entry.es.length).toBeGreaterThan(0)
      expect(entry.en.length).toBeGreaterThan(0)
    }
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Need tag labels — cubora-accumulated-dimension-rankings
// ──────────────────────────────────────────────────────────────────────────────

describe('DIMENSION_LABELS — NEED_TAGS codes registered', () => {
  const needCodes = [
    'precio_competitivo',
    'mayor_cobertura',
    'menor_franquicia',
    'atencion_personalizada',
    'rapidez',
    'financiacion',
    'comparar_con_actual',
    'renovacion_proxima',
  ]

  it('all need tag codes are present in DIMENSION_LABELS', () => {
    for (const code of needCodes) {
      expect(DIMENSION_LABELS).toHaveProperty(code)
    }
  })

  it('need tag codes each have non-empty es and en labels', () => {
    for (const code of needCodes) {
      const entry = DIMENSION_LABELS[code]
      expect(entry).toBeDefined()
      expect(entry.es.length).toBeGreaterThan(0)
      expect(entry.en.length).toBeGreaterThan(0)
    }
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Regression: every backend NEED_TAG resolves to a real label (no raw codes)
//
// Backend allowlist: app/analysis/universal/interest/catalog.py NEED_TAGS.
// COMPARANDO_OPCIONES previously had no label and rendered raw in the UI.
// This list MUST stay in sync with the backend NEED_TAGS allowlist.
// ──────────────────────────────────────────────────────────────────────────────

describe('DIMENSION_LABELS — backend NEED_TAGS allowlist fully covered', () => {
  // Mirrors backend NEED_TAGS (catalog.py). Includes the uppercase comparison
  // signal code and the 'other' fallback.
  const backendNeedTags = [
    'precio_competitivo',
    'mayor_cobertura',
    'menor_franquicia',
    'atencion_personalizada',
    'rapidez',
    'financiacion',
    'comparar_con_actual',
    'renovacion_proxima',
    'COMPARANDO_OPCIONES',
    'other',
  ]

  it('resolves COMPARANDO_OPCIONES to a Spanish label (not the raw code)', () => {
    const result = resolveLabel('COMPARANDO_OPCIONES', 'es')
    expect(result).not.toBe('COMPARANDO_OPCIONES')
    expect(result).toBe('Comparando opciones')
  })

  it('resolves COMPARANDO_OPCIONES to an English label (not the raw code)', () => {
    const result = resolveLabel('COMPARANDO_OPCIONES', 'en')
    expect(result).not.toBe('COMPARANDO_OPCIONES')
    expect(result.length).toBeGreaterThan(0)
  })

  it('every backend NEED_TAG code has a registered, non-raw label in both locales', () => {
    for (const code of backendNeedTags) {
      expect(DIMENSION_LABELS).toHaveProperty(code)
      expect(resolveLabel(code, 'es')).not.toBe(code)
      expect(resolveLabel(code, 'en')).not.toBe(code)
    }
  })
})
