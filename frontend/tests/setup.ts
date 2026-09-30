/**
 * Vitest global test setup
 *
 * 1. @testing-library/jest-dom matchers (toBeInTheDocument, etc.)
 * 2. MSW server lifecycle: start before tests, reset handlers after each, close after all
 */

import '@testing-library/jest-dom'
import { server } from './mocks/server'
import { setUnauthorizedHandler } from '../src/api/client'

// Start MSW server before all tests (intercepts fetch/XHR in Node)
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))

// jsdom cannot perform real navigation. apiFetch's default 401 handler calls
// window.location.assign, so tests get a safe no-op unless they opt into
// asserting the real redirect (see client.test.ts's dedicated reset test).
beforeEach(() => setUnauthorizedHandler(() => {}))

// Reset handlers after each test so tests don't bleed into each other
afterEach(() => server.resetHandlers())

// Shut down MSW server after all tests
afterAll(() => server.close())
