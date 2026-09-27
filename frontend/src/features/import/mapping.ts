/**
 * guessColumnMapping — auto-guesses which Qora field a CSV column maps to,
 * based on normalized header text (accent/case/space-insensitive) matched
 * against known synonyms for the built-in fields and against target field labels.
 */

export interface TargetField {
  key: string
  label: string
}

const BASE_SYNONYMS: Record<string, string[]> = {
  name: ['nombre', 'nombreyapellido', 'nombrecompleto', 'cliente', 'fullname', 'name'],
  phone: ['telefono', 'celular', 'phone', 'movil', 'whatsapp', 'numero', 'numerodetelefono', 'tel'],
  notes: ['notas', 'comentarios', 'notes', 'observaciones', 'nota', 'comentario'],
}

function normalizeHeader(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')
}

export const SKIP_FIELD_KEY = 'skip'

export function guessColumnMapping(
  headers: string[],
  targetFields: TargetField[]
): Record<string, string> {
  const normalizedTargets = targetFields.map((field) => ({
    key: field.key,
    normalizedLabel: normalizeHeader(field.label),
  }))

  const mapping: Record<string, string> = {}

  for (const header of headers) {
    const normalized = normalizeHeader(header)
    let matchedKey = SKIP_FIELD_KEY

    for (const [fieldKey, synonyms] of Object.entries(BASE_SYNONYMS)) {
      if (synonyms.includes(normalized)) {
        matchedKey = fieldKey
        break
      }
    }

    if (matchedKey === SKIP_FIELD_KEY) {
      const exactLabelMatch = normalizedTargets.find((t) => t.normalizedLabel === normalized)
      if (exactLabelMatch) matchedKey = exactLabelMatch.key
    }

    mapping[header] = matchedKey
  }

  return mapping
}
