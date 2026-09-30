import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { superadminMeFixture } from '../../../tests/mocks/auth'
import { stubLocationAssign, restoreLocation } from '../../../tests/stub-location'
import { UserMenu } from './user-menu'

function renderMenu() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <UserMenu />
    </QueryClientProvider>,
  )
}

describe('UserMenu', () => {
  it('shows the caller email and a "Cerrar sesión" action', async () => {
    renderMenu()
    expect(await screen.findByTestId('user-menu-email')).toHaveTextContent(superadminMeFixture.email!)
    expect(screen.getByRole('button', { name: 'Cerrar sesión' })).toBeInTheDocument()
  })

  it('logs out on click', async () => {
    let logoutCalled = false
    server.use(
      http.post('/api/v1/auth/logout', () => {
        logoutCalled = true
        return HttpResponse.json({ logout_url: null })
      }),
    )
    const originalLocation = window.location
    const assignMock = stubLocationAssign()

    const user = userEvent.setup()
    renderMenu()
    await user.click(await screen.findByRole('button', { name: 'Cerrar sesión' }))

    await waitFor(() => expect(assignMock).toHaveBeenCalledWith('/login'))
    expect(logoutCalled).toBe(true)

    restoreLocation(originalLocation)
  })
})
