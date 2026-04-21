/**
 * CAP-2: Design Token System Tests
 * These tests verify that tokens.css and globals.css contain the required
 * token definitions from DESIGN.md (The Sovereign Interface).
 *
 * TDD Layer: Unit — pure string/content assertions on CSS files.
 * No DOM or browser needed.
 */

import { readFileSync } from 'fs'
import { resolve } from 'path'

const tokensPath = resolve(__dirname, './tokens.css')
const globalsPath = resolve(__dirname, './globals.css')

function readCss(filePath: string): string {
  return readFileSync(filePath, 'utf-8')
}

describe('tokens.css — @theme block', () => {
  let css: string

  beforeEach(() => {
    css = readCss(tokensPath)
  })

  it('contains a @theme block', () => {
    expect(css).toMatch(/@theme\s*\{/)
  })

  // Surface hierarchy tokens
  it('defines --color-background as #0c1324', () => {
    expect(css).toContain('--color-background')
    expect(css).toContain('#0c1324')
  })

  it('defines --color-surface-container-lowest as #070d1f', () => {
    expect(css).toContain('--color-surface-container-lowest')
    expect(css).toContain('#070d1f')
  })

  it('defines --color-surface-container-low as #151b2d', () => {
    expect(css).toContain('--color-surface-container-low')
    expect(css).toContain('#151b2d')
  })

  it('defines --color-surface-container as #191f31', () => {
    expect(css).toContain('--color-surface-container')
    expect(css).toContain('#191f31')
  })

  it('defines --color-surface-bright as #33394c', () => {
    expect(css).toContain('--color-surface-bright')
    expect(css).toContain('#33394c')
  })

  // Primary accent tokens
  it('defines --color-primary as #4edea3', () => {
    expect(css).toContain('--color-primary')
    expect(css).toContain('#4edea3')
  })

  it('defines --color-primary-container as #10b981', () => {
    expect(css).toContain('--color-primary-container')
    expect(css).toContain('#10b981')
  })

  it('defines --color-on-primary as #003824', () => {
    expect(css).toContain('--color-on-primary')
    expect(css).toContain('#003824')
  })

  it('defines --color-secondary as #d0bcff', () => {
    expect(css).toContain('--color-secondary')
    expect(css).toContain('#d0bcff')
  })

  // Text tokens
  it('defines --color-on-surface-variant as #bbcabf', () => {
    expect(css).toContain('--color-on-surface-variant')
    expect(css).toContain('#bbcabf')
  })

  it('defines --color-outline as #86948a', () => {
    expect(css).toContain('--color-outline')
    expect(css).toContain('#86948a')
  })

  it('defines --color-outline-variant as #3c4a42', () => {
    expect(css).toContain('--color-outline-variant')
    expect(css).toContain('#3c4a42')
  })

  // Typography tokens
  it('defines --font-display with Manrope', () => {
    expect(css).toContain('--font-display')
    expect(css).toContain('Manrope')
  })

  it('defines --font-body with Inter', () => {
    expect(css).toContain('--font-body')
    expect(css).toContain('Inter')
  })

  // Radius tokens
  it('defines --radius-DEFAULT as 0.25rem', () => {
    expect(css).toContain('--radius-DEFAULT')
    expect(css).toContain('0.25rem')
  })

  it('defines --radius-sm as 0.125rem', () => {
    expect(css).toContain('--radius-sm')
    expect(css).toContain('0.125rem')
  })
})

describe('globals.css — structure', () => {
  let css: string

  beforeEach(() => {
    css = readCss(globalsPath)
  })

  it('imports tailwindcss', () => {
    expect(css).toMatch(/@import\s+["']tailwindcss["']/)
  })

  it('imports tokens.css', () => {
    expect(css).toMatch(/@import\s+["']\.\/tokens\.css["']/)
  })

  it('contains @font-face for Manrope', () => {
    expect(css).toContain('@font-face')
    expect(css).toContain('Manrope')
  })

  it('contains @font-face for Inter', () => {
    expect(css).toContain('@font-face')
    expect(css).toContain('Inter')
  })
})
