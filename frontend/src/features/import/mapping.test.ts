import { describe, it, expect } from 'vitest'
import { guessColumnMapping, SKIP_FIELD_KEY, type TargetField } from './mapping'

const targetFields: TargetField[] = [
  { key: 'name', label: 'Nombre' },
  { key: 'phone', label: 'Teléfono' },
  { key: 'notes', label: 'Notas' },
  { key: 'car_make', label: 'Marca' },
  { key: 'car_model', label: 'Modelo' },
]

describe('guessColumnMapping', () => {
  it('maps common Spanish header synonyms to built-in fields', () => {
    const mapping = guessColumnMapping(
      ['Nombre y apellido', 'Celular', 'Comentarios'],
      targetFields
    )
    expect(mapping['Nombre y apellido']).toBe('name')
    expect(mapping['Celular']).toBe('phone')
    expect(mapping['Comentarios']).toBe('notes')
  })

  it('is accent and case insensitive', () => {
    const mapping = guessColumnMapping(['TELÉFONO', 'nombre'], targetFields)
    expect(mapping['TELÉFONO']).toBe('phone')
    expect(mapping['nombre']).toBe('name')
  })

  it('matches custom field labels exactly', () => {
    const mapping = guessColumnMapping(['Marca', 'Modelo'], targetFields)
    expect(mapping['Marca']).toBe('car_make')
    expect(mapping['Modelo']).toBe('car_model')
  })

  it('defaults unrecognized headers to skip', () => {
    const mapping = guessColumnMapping(['Columna rara'], targetFields)
    expect(mapping['Columna rara']).toBe(SKIP_FIELD_KEY)
  })
})
