import { act, renderHook } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import { useTheme, useSidebarCollapsed, getStoredTheme, getStoredCollapsed } from './theme'

describe('theme persistence', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('defaults to dark theme when nothing is stored', () => {
    expect(getStoredTheme()).toBe('dark')
  })

  it('useTheme sets data-theme on <html> and persists to localStorage on toggle', () => {
    const { result } = renderHook(() => useTheme())
    expect(result.current[0]).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    act(() => result.current[1]())

    expect(result.current[0]).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(window.localStorage.getItem('qora-theme')).toBe('light')
  })

  it('useTheme reads the persisted value back on next mount', () => {
    window.localStorage.setItem('qora-theme', 'light')
    const { result } = renderHook(() => useTheme())
    expect(result.current[0]).toBe('light')
  })
})

describe('sidebar collapsed persistence', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('defaults to expanded (false) when nothing is stored', () => {
    expect(getStoredCollapsed()).toBe(false)
  })

  it('useSidebarCollapsed persists toggled state to localStorage', () => {
    const { result } = renderHook(() => useSidebarCollapsed())
    expect(result.current[0]).toBe(false)

    act(() => result.current[1]())

    expect(result.current[0]).toBe(true)
    expect(window.localStorage.getItem('qora-sidebar-collapsed')).toBe('true')
  })

  it('useSidebarCollapsed reads the persisted value back on next mount', () => {
    window.localStorage.setItem('qora-sidebar-collapsed', 'true')
    const { result } = renderHook(() => useSidebarCollapsed())
    expect(result.current[0]).toBe(true)
  })
})
