/**
 * MSW Server setup
 *
 * Uses msw/node for Vitest (Node.js environment with jsdom).
 * The server is started in tests/setup.ts via beforeAll/afterEach/afterAll.
 */

import { setupServer } from 'msw/node'
import { handlers } from './handlers'

export const server = setupServer(...handlers)
