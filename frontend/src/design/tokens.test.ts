/**
 * Design Token System Tests — Qora Design System
 *
 * Verifies that tokens.css and globals.css contain the required
 * Qora-native token definitions (replaces Material/Sovereign Interface).
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

  // Canvas tokens
  it('defines --color-pearl as #F2F4F3', () => {
    expect(css).toContain('--color-pearl')
    expect(css).toContain('#F2F4F3')
  })

  it('defines --color-paper as #FFFFFF', () => {
    expect(css).toContain('--color-paper')
    expect(css).toContain('#FFFFFF')
  })

  it('defines --color-mist as #E8ECEB', () => {
    expect(css).toContain('--color-mist')
    expect(css).toContain('#E8ECEB')
  })

  it('defines --color-smoke as #D6DAD9', () => {
    expect(css).toContain('--color-smoke')
    expect(css).toContain('#D6DAD9')
  })

  // Ink hierarchy tokens
  it('defines --color-ink as #0E1217', () => {
    expect(css).toContain('--color-ink:')
    expect(css).toContain('#0E1217')
  })

  it('defines --color-ink-2 as #44474D', () => {
    expect(css).toContain('--color-ink-2')
    expect(css).toContain('#44474D')
  })

  it('defines --color-ink-3 as #767880', () => {
    expect(css).toContain('--color-ink-3')
    expect(css).toContain('#767880')
  })

  // Brand tokens
  it('defines --color-teal as #1A8B7A', () => {
    expect(css).toContain('--color-teal:')
    expect(css).toContain('#1A8B7A')
  })

  it('defines --color-teal-deep as #0E4E45', () => {
    expect(css).toContain('--color-teal-deep')
    expect(css).toContain('#0E4E45')
  })

  it('defines --color-teal-faint', () => {
    expect(css).toContain('--color-teal-faint')
    expect(css).toContain('rgba(26,139,122,0.08)')
  })

  it('defines --color-teal-line', () => {
    expect(css).toContain('--color-teal-line')
    expect(css).toContain('rgba(26,139,122,0.28)')
  })

  // Accent tokens
  it('defines --color-coral as #E0764F', () => {
    expect(css).toContain('--color-coral:')
    expect(css).toContain('#E0764F')
  })

  it('defines --color-coral-faint', () => {
    expect(css).toContain('--color-coral-faint')
    expect(css).toContain('rgba(224,118,79,0.09)')
  })

  // Line tokens
  it('defines --color-line', () => {
    expect(css).toContain('--color-line:')
    expect(css).toContain('rgba(14,18,23,0.08)')
  })

  it('defines --color-line-2', () => {
    expect(css).toContain('--color-line-2')
    expect(css).toContain('rgba(14,18,23,0.14)')
  })

  // Typography tokens
  it('defines --font-display with Fredoka', () => {
    expect(css).toContain('--font-display')
    expect(css).toContain('Fredoka')
  })

  it('defines --font-body with Inter', () => {
    expect(css).toContain('--font-body')
    expect(css).toContain('Inter')
  })

  it('defines --font-mono with JetBrains Mono', () => {
    expect(css).toContain('--font-mono')
    expect(css).toContain('JetBrains Mono')
  })

  // Radius tokens — Qora scale (not old 0.25rem)
  it('defines --radius-DEFAULT as 12px', () => {
    expect(css).toContain('--radius-DEFAULT')
    expect(css).toContain('12px')
  })

  it('defines --radius-full as 999px (pill)', () => {
    expect(css).toContain('--radius-full')
    expect(css).toContain('999px')
  })

  it('defines --radius-lg as 20px', () => {
    expect(css).toContain('--radius-lg')
    expect(css).toContain('20px')
  })

  // Shadow tokens
  it('defines --shadow-md', () => {
    expect(css).toContain('--shadow-md')
    expect(css).toContain('rgba(14,18,23,0.06)')
  })

  // Layout tokens
  it('defines --spacing-sidebar', () => {
    expect(css).toContain('--spacing-sidebar')
  })

  it('defines --spacing-topbar', () => {
    expect(css).toContain('--spacing-topbar')
  })

  // Old Sovereign Interface tokens must NOT be present
  it('does NOT contain old Obsidian background #0c1324', () => {
    expect(css).not.toContain('#0c1324')
  })

  it('does NOT contain --color-primary (Material naming removed)', () => {
    expect(css).not.toContain('--color-primary:')
    expect(css).not.toContain('--color-primary-container')
  })

  it('does NOT contain --color-surface-container (Material naming removed)', () => {
    expect(css).not.toContain('--color-surface-container:')
    expect(css).not.toContain('--color-surface-container-low')
  })

  it('does NOT contain --color-on-surface (Material naming removed)', () => {
    expect(css).not.toContain('--color-on-surface:')
    expect(css).not.toContain('--color-on-surface-variant')
  })

  it('does NOT contain Manrope (banned font)', () => {
    expect(css).not.toContain('Manrope')
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

  it('imports Google Fonts (Fredoka + Inter + JetBrains Mono)', () => {
    expect(css).toContain('fonts.googleapis.com')
    expect(css).toContain('Fredoka')
    expect(css).toContain('Inter')
    expect(css).toContain('JetBrains+Mono')
  })

  it('does NOT contain @font-face for Manrope (self-hosted Manrope removed)', () => {
    // Manrope @font-face blocks are removed — using Google Fonts CDN
    const manropeFontFace = css.match(/@font-face[\s\S]*?Manrope/)
    expect(manropeFontFace).toBeNull()
  })

  it('sets body background-color to var(--color-pearl)', () => {
    expect(css).toContain('background-color: var(--color-pearl)')
  })

  it('sets body color to var(--color-ink)', () => {
    expect(css).toContain('color: var(--color-ink)')
  })

  it('has :focus-visible with teal ring', () => {
    expect(css).toContain(':focus-visible')
    expect(css).toContain('var(--color-teal-faint)')
  })

  it('does NOT contain hardcoded background #0c1324 (dark mode removed)', () => {
    expect(css).not.toContain('#0c1324')
  })

  it('does NOT contain hardcoded color #e2e8f0 (on-surface removed)', () => {
    expect(css).not.toContain('#e2e8f0')
  })
})
