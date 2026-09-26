/**
 * Theme + sidebar-collapse persistence for the dashboard shell.
 * Default theme is 'dark'; Tailwind @theme tokens have dark overrides in tokens.css.
 */

import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const THEME_KEY = 'qora-theme'
const COLLAPSED_KEY = 'qora-sidebar-collapsed'

export function getStoredTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  return window.localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
}

export function getStoredCollapsed(): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(COLLAPSED_KEY) === 'true'
}

/** Manages `theme` state, mirrors it to <html data-theme> and localStorage. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => getStoredTheme())

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    window.localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  const toggle = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  return [theme, toggle]
}

/** Manages sidebar `collapsed` state, mirrors it to localStorage. */
export function useSidebarCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState<boolean>(() => getStoredCollapsed())

  useEffect(() => {
    window.localStorage.setItem(COLLAPSED_KEY, String(collapsed))
  }, [collapsed])

  const toggle = () => setCollapsed((c) => !c)

  return [collapsed, toggle]
}
