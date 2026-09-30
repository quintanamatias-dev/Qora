/**
 * Auth MSW fixtures — default is an authenticated superadmin session so
 * existing tests that render through RequireAuth keep passing unless they
 * opt into a different identity via server.use().
 */

import { http, HttpResponse } from 'msw'
import type { AuthConfig, CallerMe } from '../../src/api/auth'

export const superadminMeFixture: CallerMe = {
  auth_method: 'session',
  role: 'superadmin',
  email: 'admin@qora.dev',
  name: 'Qora Admin',
  client_ids: [],
}

export function makeClientMe(overrides: Partial<CallerMe> = {}): CallerMe {
  return {
    auth_method: 'session',
    role: 'client',
    email: 'owner@acme-motors.com',
    name: 'Acme Owner',
    client_ids: ['acme-motors'],
    ...overrides,
  }
}

export const authConfigFixture: AuthConfig = { login_enabled: true }

export const authHandlers = [
  http.get('/api/v1/auth/me', () => HttpResponse.json(superadminMeFixture)),
  http.get('/api/v1/auth/config', () => HttpResponse.json(authConfigFixture)),
  http.post('/api/v1/auth/logout', () => HttpResponse.json({ logout_url: null })),
]
