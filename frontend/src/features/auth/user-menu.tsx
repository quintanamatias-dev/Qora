/**
 * UserMenu — email + "Cerrar sesión" shown in both layouts (multi-tenant-auth §9)
 *
 * A failed logout keeps the user on the page with an inline error, so they
 * know the session is still open and can retry.
 */

import { useState } from 'react'
import { useMe, logout } from '@/api/auth'

export function UserMenu() {
  const { data } = useMe()
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutFailed, setLogoutFailed] = useState(false)

  if (!data) return null

  async function handleLogout() {
    setIsLoggingOut(true)
    setLogoutFailed(false)
    try {
      await logout()
    } catch {
      setLogoutFailed(true)
      setIsLoggingOut(false)
    }
  }

  return (
    <div data-testid="user-menu" className="flex items-center gap-3 text-sm">
      <span className="text-ink-3" data-testid="user-menu-email">
        {data.email}
      </span>
      {logoutFailed && (
        <span role="alert" className="text-xs text-error">
          No se pudo cerrar la sesión. Intentá de nuevo.
        </span>
      )}
      <button
        type="button"
        onClick={() => void handleLogout()}
        disabled={isLoggingOut}
        className="text-ink-3 hover:text-ink transition-colors disabled:opacity-50"
      >
        Cerrar sesión
      </button>
    </div>
  )
}
