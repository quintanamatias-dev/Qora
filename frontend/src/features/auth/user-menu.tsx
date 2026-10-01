/**
 * UserMenu — email + "Cerrar sesión" shown in both layouts (multi-tenant-auth §9)
 */

import { useMe, logout } from '@/api/auth'

export function UserMenu() {
  const { data } = useMe()

  if (!data) return null

  return (
    <div data-testid="user-menu" className="flex items-center gap-3 text-sm">
      <span className="text-ink-3" data-testid="user-menu-email">
        {data.email}
      </span>
      <button
        type="button"
        onClick={() => void logout()}
        className="text-ink-3 hover:text-ink transition-colors"
      >
        Cerrar sesión
      </button>
    </div>
  )
}
