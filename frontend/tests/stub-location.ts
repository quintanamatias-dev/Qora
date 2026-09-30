import { vi } from 'vitest'

/**
 * jsdom's window.location.assign is neither spy-able nor reassignable through
 * normal property assignment (TS types window.location as `string & Location`).
 * Object.defineProperty bypasses both restrictions for the duration of a test.
 */
export function stubLocationAssign(): ReturnType<typeof vi.fn> {
  const assignMock = vi.fn()
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: { ...window.location, assign: assignMock },
  })
  return assignMock
}

export function restoreLocation(original: Location): void {
  Object.defineProperty(window, 'location', {
    writable: true,
    configurable: true,
    value: original,
  })
}
