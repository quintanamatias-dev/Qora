import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { stubLocationAssign, restoreLocation } from '../../../tests/stub-location'
import { LoginPage } from './login-page'

const originalLocation = window.location

afterEach(() => {
  restoreLocation(originalLocation)
})

function renderAt(initialEntry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const router = createMemoryRouter([{ path: '/login', element: <LoginPage /> }], {
    initialEntries: [initialEntry],
  })
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('LoginPage', () => {
  it('renders the Qora brand and the "Iniciar sesión" button', async () => {
    renderAt('/login')
    expect(screen.getByText('Qora')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Iniciar sesión' })).toBeEnabled())
  })

  it('navigates to the login endpoint with the sanitized return_to on click', async () => {
    const assignMock = stubLocationAssign()
    const user = userEvent.setup()
    renderAt('/login?return_to=%2Fapp%2Facme-motors%2Fleads')

    await user.click(await screen.findByRole('button', { name: 'Iniciar sesión' }))

    expect(assignMock).toHaveBeenCalledWith(
      `/api/v1/auth/login?return_to=${encodeURIComponent('/app/acme-motors/leads')}`,
    )
  })

  it('defaults return_to to / when the query value is unsafe', async () => {
    const assignMock = stubLocationAssign()
    const user = userEvent.setup()
    renderAt('/login?return_to=%2F%2Fevil.com')

    await user.click(await screen.findByRole('button', { name: 'Iniciar sesión' }))

    expect(assignMock).toHaveBeenCalledWith(`/api/v1/auth/login?return_to=${encodeURIComponent('/')}`)
  })

  it.each([
    ['auth_not_configured', 'El inicio de sesión no está configurado.'],
    ['invalid_state', 'La sesión de inicio de sesión expiró o no es válida. Probá de nuevo.'],
    ['login_failed', 'No pudimos iniciar sesión. Probá de nuevo.'],
    ['organization_selection_required', 'Tu cuenta pertenece a más de una organización. Contactá a un administrador.'],
    ['no_access', 'Tu cuenta no tiene acceso a Qora. Contactá a un administrador.'],
  ])('shows the message for error=%s', async (code, message) => {
    renderAt(`/login?error=${code}`)
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('shows the not-configured message and disables the button when login_enabled is false', async () => {
    server.use(http.get('/api/v1/auth/config', () => HttpResponse.json({ login_enabled: false })))
    renderAt('/login')
    expect(await screen.findByRole('alert')).toHaveTextContent('El inicio de sesión no está configurado.')
    expect(screen.getByRole('button', { name: 'Iniciar sesión' })).toBeDisabled()
  })
})
