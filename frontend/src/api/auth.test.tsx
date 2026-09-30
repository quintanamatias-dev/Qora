/**
 * Auth API tests (multi-tenant-auth §7, §9)
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../tests/mocks/server'
import { superadminMeFixture } from '../../tests/mocks/auth'
import { stubLocationAssign, restoreLocation } from '../../tests/stub-location'
import { getAuthConfig, getMe, logout, useMe } from './auth'

const originalLocation = window.location

afterEach(() => {
  vi.restoreAllMocks()
  restoreLocation(originalLocation)
})

describe('getAuthConfig', () => {
  it('fetches /api/v1/auth/config', async () => {
    const result = await getAuthConfig()
    expect(result).toEqual({ login_enabled: true })
  })
})

describe('getMe', () => {
  it('fetches /api/v1/auth/me', async () => {
    const result = await getMe()
    expect(result).toEqual(superadminMeFixture)
  })
})

describe('logout', () => {
  it('POSTs /api/v1/auth/logout then navigates to the returned logout_url', async () => {
    server.use(http.post('/api/v1/auth/logout', () => HttpResponse.json({ logout_url: 'https://api.workos.com/logout/sid-1' })))
    const assignMock = stubLocationAssign()

    await logout()

    expect(assignMock).toHaveBeenCalledWith('https://api.workos.com/logout/sid-1')
  })

  it('navigates to /login when logout_url is null', async () => {
    server.use(http.post('/api/v1/auth/logout', () => HttpResponse.json({ logout_url: null })))
    const assignMock = stubLocationAssign()

    await logout()

    expect(assignMock).toHaveBeenCalledWith('/login')
  })
})

function renderUseMe() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  function Probe() {
    const { data, isLoading, isError } = useMe()
    if (isLoading) return <p>loading</p>
    if (isError) return <p>error</p>
    return <p>{data?.email}</p>
  }
  return render(
    <QueryClientProvider client={qc}>
      <Probe />
    </QueryClientProvider>,
  )
}

describe('useMe', () => {
  it('resolves with the caller identity', async () => {
    renderUseMe()
    expect(await screen.findByText(superadminMeFixture.email!)).toBeInTheDocument()
  })

  it('does not retry on a 401', async () => {
    let calls = 0
    server.use(
      http.get('/api/v1/auth/me', () => {
        calls += 1
        return HttpResponse.json({ error: { message: 'Session expired or invalid' } }, { status: 401 })
      }),
    )
    renderUseMe()
    await waitFor(() => expect(screen.getByText('error')).toBeInTheDocument())
    expect(calls).toBe(1)
  })
})
