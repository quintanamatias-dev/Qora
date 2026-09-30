/**
 * LoginPage — public entry point for WorkOS AuthKit login (multi-tenant-auth §9)
 *
 * Not wrapped in RequireAuth. Reads `return_to` and `error` from the query
 * string; "Iniciar sesión" performs a full navigation to the backend, which
 * redirects to the WorkOS hosted login page.
 */

import { useSearchParams } from 'react-router'
import { Button, Card } from '@/design/components'
import { useAuthConfig } from '@/api/auth'
import { sanitizeReturnTo } from './return-to'

const ERROR_MESSAGES: Record<string, string> = {
  auth_not_configured: 'El inicio de sesión no está configurado.',
  invalid_state: 'La sesión de inicio de sesión expiró o no es válida. Probá de nuevo.',
  login_failed: 'No pudimos iniciar sesión. Probá de nuevo.',
  organization_selection_required: 'Tu cuenta pertenece a más de una organización. Contactá a un administrador.',
  no_access: 'Tu cuenta no tiene acceso a Qora. Contactá a un administrador.',
}

export function LoginPage() {
  const [searchParams] = useSearchParams()
  const config = useAuthConfig()

  const returnTo = sanitizeReturnTo(searchParams.get('return_to'))
  const errorCode = searchParams.get('error')

  const loginDisabled = config.data ? !config.data.login_enabled : false
  const message = loginDisabled
    ? ERROR_MESSAGES.auth_not_configured
    : errorCode
      ? (ERROR_MESSAGES[errorCode] ?? null)
      : null

  function handleLogin() {
    window.location.assign(`/api/v1/auth/login?return_to=${encodeURIComponent(returnTo)}`)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-pearl px-4">
      <Card className="w-full max-w-sm text-center space-y-6">
        <div>
          <span className="font-display text-2xl font-semibold text-teal tracking-tight">Qora</span>
        </div>

        {message && (
          <p role="alert" className="text-sm text-coral">
            {message}
          </p>
        )}

        <Button onClick={handleLogin} disabled={loginDisabled || config.isLoading} className="w-full">
          Iniciar sesión
        </Button>
      </Card>
    </div>
  )
}
