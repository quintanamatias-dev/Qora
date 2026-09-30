/**
 * ImportPage — Integration tests
 *
 * Mocks src/api/leads.ts, src/api/hooks.ts (useIntegrations) and the local
 * crm-import.ts module directly with vi.mock, instead of editing the shared
 * MSW handlers in tests/mocks — those are used by other features in parallel.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider, Outlet } from 'react-router'
import { ImportPage } from './page'
import type { IntegrationConfig } from '@/api/types'

const { createLeadMock } = vi.hoisted(() => ({ createLeadMock: vi.fn() }))
vi.mock('@/api/leads', () => ({
  createLead: createLeadMock,
}))

const { useIntegrationsMock } = vi.hoisted(() => ({ useIntegrationsMock: vi.fn() }))
vi.mock('@/api/hooks', () => ({
  useIntegrations: useIntegrationsMock,
  // Unrestricted plan — plan gating is covered in features/entitlements.
  useEntitlements: () => ({ data: undefined, isLoading: false }),
}))

const { triggerCrmImportMock } = vi.hoisted(() => ({ triggerCrmImportMock: vi.fn() }))
vi.mock('./crm-import', () => ({
  triggerCrmImport: triggerCrmImportMock,
}))

function renderImportPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } })
  const router = createMemoryRouter(
    [
      {
        path: '/app/:clientId',
        element: <Outlet />,
        children: [{ path: 'import', element: <ImportPage /> }],
      },
    ],
    { initialEntries: ['/app/demo-client/import'] }
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { qc }
}

function makeCsvFile(content: string, name = 'leads.csv') {
  return new File([content], name, { type: 'text/csv' })
}

const CONNECTED_INTEGRATION: IntegrationConfig = {
  provider: 'airtable',
  base_id: 'appXXXX',
  table_id: 'tblSWUmWWFEOqKWID',
  api_key_env: 'QORA_DEMO_AIRTABLE_API_KEY',
  match_field: 'lead_id',
  field_count: 5,
  connected: true,
  field_mappings: [
    { source: 'name', target: 'Name', type: 'string', required: true },
    { source: 'phone', target: 'Phone', type: 'phone', required: true },
  ],
  field_definitions: [{ field_key: 'car_make', field_type: 'string', label: 'Marca' }],
  quote_ready_fields: [],
}

beforeEach(() => {
  createLeadMock.mockReset()
  triggerCrmImportMock.mockReset()
  useIntegrationsMock.mockReset()
  useIntegrationsMock.mockReturnValue({ data: [], isLoading: false })
})

describe('ImportPage — heading and empty CRM state', () => {
  it('renders the "Importar" heading', async () => {
    renderImportPage()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Importar' })).toBeInTheDocument())
  })

  it('shows an honest empty state when no CRM integration is configured', async () => {
    renderImportPage()
    await waitFor(() =>
      expect(screen.getByText(/todavía no tiene un CRM configurado/i)).toBeInTheDocument()
    )
  })
})

describe('ImportPage — CSV upload and mapping', () => {
  it('parses the file, guesses the mapping, and shows real row/column counts', async () => {
    const user = userEvent.setup()
    renderImportPage()

    const file = makeCsvFile('Nombre,Celular\nLucia Ramirez,+5491122223333\nJuan Perez,+5491133334444\n')
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, file)

    await waitFor(() => expect(screen.getByText('leads.csv')).toBeInTheDocument())
    expect(screen.getByText('2 filas · 2 columnas')).toBeInTheDocument()
    expect(screen.getByText('Lucia Ramirez')).toBeInTheDocument()
  })

  it('omits rows missing a valid phone from the import count', async () => {
    const user = userEvent.setup()
    renderImportPage()

    const file = makeCsvFile('Nombre,Celular\nLucia Ramirez,+5491122223333\nSin Telefono,\n')
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, file)

    await waitFor(() => expect(screen.getByText('leads.csv')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Importar 1 lead' })).toBeInTheDocument()
    expect(screen.getByText(/1 fila.*se van a omitir/)).toBeInTheDocument()
  })

  it('creates leads via createLead, reports failures, and shows the real result count', async () => {
    createLeadMock.mockImplementation(async (_clientId: string, payload: { phone: string }) => {
      if (payload.phone === '+5491133334444') throw Object.assign(new Error('Duplicado'), { name: 'ApiError' })
      return { id: 'lead-1', ...payload }
    })

    const user = userEvent.setup()
    renderImportPage()

    const file = makeCsvFile(
      'Nombre,Celular\nLucia Ramirez,+5491122223333\nJuan Perez,+5491133334444\n'
    )
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, file)

    await waitFor(() => expect(screen.getByText('leads.csv')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Importar 2 leads' }))

    await waitFor(() => expect(screen.getAllByText('1 lead importado').length).toBeGreaterThan(0))
    expect(createLeadMock).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Duplicado')).toBeInTheDocument()
  })
})

describe('ImportPage — CRM sync', () => {
  it('shows real integration details and syncs via the CRM import endpoint', async () => {
    useIntegrationsMock.mockReturnValue({ data: [CONNECTED_INTEGRATION], isLoading: false })
    triggerCrmImportMock.mockResolvedValue({ created: 3, updated: 2, skipped: 0, errors: [] })

    const user = userEvent.setup()
    renderImportPage()

    await waitFor(() => expect(screen.getByText('Airtable')).toBeInTheDocument())
    expect(screen.getByText('tblSWUmWWFEOqKWID')).toBeInTheDocument()
    expect(screen.getByText('Sin registro')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Sincronizar ahora/i }))

    await waitFor(() => expect(triggerCrmImportMock).toHaveBeenCalledWith('demo-client'))
    await waitFor(() => expect(screen.getByText('Hace un momento')).toBeInTheDocument())
    expect(screen.getByText(/3 creados · 2 actualizados/)).toBeInTheDocument()
  })
})
