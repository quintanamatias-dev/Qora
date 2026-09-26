/**
 * parseCsv — dependency-free CSV parser.
 *
 * Handles: BOM stripping, comma/semicolon delimiter auto-detection,
 * quoted fields (including escaped "" quotes and embedded delimiters/newlines),
 * and CRLF/LF line endings.
 */

export interface ParsedCsv {
  headers: string[]
  rows: string[][]
}

function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
}

function detectDelimiter(text: string): string {
  const firstLine = text.split(/\r\n|\r|\n/)[0] ?? ''
  let commas = 0
  let semicolons = 0
  let inQuotes = false
  for (let i = 0; i < firstLine.length; i++) {
    const char = firstLine[i]
    if (char === '"') {
      if (inQuotes && firstLine[i + 1] === '"') {
        i += 1
        continue
      }
      inQuotes = !inQuotes
      continue
    }
    if (inQuotes) continue
    if (char === ',') commas += 1
    else if (char === ';') semicolons += 1
  }
  return semicolons > commas ? ';' : ','
}

export function parseCsv(input: string): ParsedCsv {
  const text = stripBom(input)
  if (!text.trim()) return { headers: [], rows: [] }

  const delimiter = detectDelimiter(text)
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  let i = 0
  const len = text.length

  while (i < len) {
    const char = text[i]

    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i += 2
          continue
        }
        inQuotes = false
        i += 1
        continue
      }
      field += char
      i += 1
      continue
    }

    if (char === '"') {
      inQuotes = true
      i += 1
      continue
    }
    if (char === delimiter) {
      row.push(field)
      field = ''
      i += 1
      continue
    }
    if (char === '\r') {
      i += 1
      continue
    }
    if (char === '\n') {
      row.push(field)
      field = ''
      rows.push(row)
      row = []
      i += 1
      continue
    }
    field += char
    i += 1
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field)
    rows.push(row)
  }

  const nonEmpty = rows.filter((r) => !(r.length === 1 && r[0] === ''))
  const [headerRow, ...dataRows] = nonEmpty
  const headers = (headerRow ?? []).map((h) => h.trim())
  return { headers, rows: dataRows }
}
