/**
 * CAP-5: Leads API endpoint function tests
 *
 * REQ-5.2: typed endpoint functions call correct URL paths
 */

import { describe, it, expect, afterEach, vi } from 'vitest'
import { fetchLeads, fetchLead, createLead } from './leads'
import type { Lead, CreateLeadPayload } from './types'

// ──────────────────────────────────────────────────────────────────────────────
// Fixtures
// ──────────────────────────────────────────────────────────────────────────────
const mockLead: Lead = {
  id: 'lead-1',
  client_id: 'demo-client',
  name: 'John Doe',
  phone: '+1-555-0100',
  // Transition: legacy fields still present
  car_make: 'Toyota',
  car_model: 'Camry',
  car_year: 2022,
  current_insurance: 'State Farm',
  status: 'new',
  notes: null,
  call_count: 0,
  last_called_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: null,
  // Phase 2 CRM fields
  summary_last_call: null,
  objections_heard: null,
  interest_level: null,
  extracted_facts: null,
  do_not_call: false,
  next_action: null,
  next_action_at: null,
  // Phase 7
  next_scheduled_call_at: null,
  // WU-6: custom fields
  custom_fields: { car_make: 'Toyota', car_model: 'Camry', car_year: '2022' },
}

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    )
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchLeads
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchLeads', () => {
  it('calls /api/v1/leads?client_id=<clientId> and returns array', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([mockLead]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    )
    vi.stubGlobal('fetch', fetchSpy)

    const result = await fetchLeads('demo-client')

    expect(result).toHaveLength(1)
    expect(result[0].name).toBe('John Doe')
    const calledUrl = fetchSpy.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/leads')
    expect(calledUrl).toContain('client_id=demo-client')
  })

  it('returns empty array when no leads exist', async () => {
    mockFetch(200, [])
    const result = await fetchLeads('acme-motors')
    expect(result).toHaveLength(0)
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// fetchLead
// ──────────────────────────────────────────────────────────────────────────────
describe('fetchLead', () => {
  it('calls /api/v1/leads/:leadId and returns single lead', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(mockLead), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    )
    vi.stubGlobal('fetch', fetchSpy)

    const result = await fetchLead('demo-client', 'lead-1')

    expect(result.id).toBe('lead-1')
    expect(result.name).toBe('John Doe')
    const calledUrl = fetchSpy.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/leads/lead-1')
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// createLead
// ──────────────────────────────────────────────────────────────────────────────
describe('createLead', () => {
  it('calls POST /api/v1/leads?client_id=<clientId> and returns created lead', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(mockLead), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      })
    )
    vi.stubGlobal('fetch', fetchSpy)

    const payload: CreateLeadPayload = { name: 'John Doe', phone: '+1-555-0100' }
    const result = await createLead('demo-client', payload)

    expect(result.id).toBe('lead-1')
    const calledUrl = fetchSpy.mock.calls[0][0] as string
    expect(calledUrl).toContain('/api/v1/leads')
    expect(calledUrl).toContain('client_id=demo-client')
    // Method must be POST
    const calledInit = fetchSpy.mock.calls[0][1] as RequestInit
    expect(calledInit.method).toBe('POST')
  })
})
