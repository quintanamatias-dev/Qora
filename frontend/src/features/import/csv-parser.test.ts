import { describe, it, expect } from 'vitest'
import { parseCsv } from './csv-parser'

describe('parseCsv', () => {
  it('parses a simple comma-delimited CSV with headers', () => {
    const result = parseCsv('Nombre,Telefono\nLucia,+5491122223333\n')
    expect(result.headers).toEqual(['Nombre', 'Telefono'])
    expect(result.rows).toEqual([['Lucia', '+5491122223333']])
  })

  it('strips a UTF-8 BOM before parsing', () => {
    const result = parseCsv('\uFEFFNombre,Telefono\nLucia,111\n')
    expect(result.headers).toEqual(['Nombre', 'Telefono'])
  })

  it('detects semicolon delimiter when it dominates the header row', () => {
    const result = parseCsv('Nombre;Telefono;Notas\nJuan;222;Vino de Meta Ads\n')
    expect(result.headers).toEqual(['Nombre', 'Telefono', 'Notas'])
    expect(result.rows).toEqual([['Juan', '222', 'Vino de Meta Ads']])
  })

  it('handles CRLF line endings', () => {
    const result = parseCsv('Nombre,Telefono\r\nAna,333\r\nLuis,444\r\n')
    expect(result.rows).toEqual([
      ['Ana', '333'],
      ['Luis', '444'],
    ])
  })

  it('handles quoted fields with embedded commas', () => {
    const result = parseCsv('Nombre,Notas\n"Perez, Juan","Vino de Facebook, campaña de otoño"\n')
    expect(result.rows).toEqual([['Perez, Juan', 'Vino de Facebook, campaña de otoño']])
  })

  it('unescapes doubled quotes inside a quoted field', () => {
    const result = parseCsv('Nombre,Notas\n"Ana","Dijo ""llamame despues"""\n')
    expect(result.rows).toEqual([['Ana', 'Dijo "llamame despues"']])
  })

  it('handles a quoted field containing a newline', () => {
    const result = parseCsv('Nombre,Notas\n"Ana","Linea uno\nLinea dos"\nLuis,ok\n')
    expect(result.rows).toEqual([
      ['Ana', 'Linea uno\nLinea dos'],
      ['Luis', 'ok'],
    ])
  })

  it('returns empty headers and rows for blank input', () => {
    expect(parseCsv('')).toEqual({ headers: [], rows: [] })
    expect(parseCsv('   \n  ')).toEqual({ headers: [], rows: [] })
  })

  it('parses a trailing row without a final newline', () => {
    const result = parseCsv('Nombre,Telefono\nAna,111\nLuis,222')
    expect(result.rows).toEqual([
      ['Ana', '111'],
      ['Luis', '222'],
    ])
  })
})
