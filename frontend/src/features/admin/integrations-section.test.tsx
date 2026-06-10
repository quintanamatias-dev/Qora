/**
 * IntegrationsSection tests — T18 + Connect/Disconnect flow
 *
 * Verifies:
 * - Loading state shown initially
 * - Available (not-connected) state for clients without a connected integration
 * - Connected integration card rendered for quintana-seguros
 * - Connected badge shown when integration.connected = true
 * - "Test Connection" button present in expanded details
 * - api_key_env shown as env var name (not a raw secret)
 * - Test connection success/failure toast
 * - Connect button expands the connect form for not-connected integrations
 * - Disconnect button calls DELETE endpoint and shows toast
 */

import { describe, it, expect } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { http, HttpResponse } from 'msw'
import { server } from '../../../tests/mocks/server'
import { IntegrationsSection } from './integrations-section'

function renderIntegrationsSection(clientId: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <IntegrationsSection clientId={clientId} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Loading state
// ──────────────────────────────────────────────────────────────────────────────

describe('IntegrationsSection — loading', () => {
  it('shows loading skeleton initially', () => {
    renderIntegrationsSection('quintana-seguros')
    expect(screen.getByTestId('integrations-loading')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Available (not connected) state
// ──────────────────────────────────────────────────────────────────────────────

describe('IntegrationsSection — available (not connected)', () => {
  it('shows Airtable as available for client with no connected integration', async () => {
    renderIntegrationsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('integrations-available')).toBeInTheDocument()
    // The provider name shown as a heading (exact text match to avoid matching description)
    expect(screen.getByText('Airtable')).toBeInTheDocument()
  })

  it('shows Connect button for not-connected provider', async () => {
    renderIntegrationsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('connect-button-airtable')).toBeInTheDocument()
  })

  it('clicking Connect expands the connect form', async () => {
    renderIntegrationsSection('demo-client')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const connectBtn = screen.getByTestId('connect-button-airtable')
    await userEvent.click(connectBtn)
    expect(screen.getByTestId('connect-form-airtable')).toBeInTheDocument()
    expect(screen.getByTestId('connect-api-key-env-input')).toBeInTheDocument()
    expect(screen.getByTestId('connect-base-id-input')).toBeInTheDocument()
    expect(screen.getByTestId('connect-table-id-input')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────────────────────
// Connected state — quintana-seguros has Airtable configured
// ──────────────────────────────────────────────────────────────────────────────

describe('IntegrationsSection — connected (quintana-seguros)', () => {
  it('shows the integration list after loading', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('integrations-list')).toBeInTheDocument()
  })

  it('shows the provider name (airtable)', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByText(/airtable/i)).toBeInTheDocument()
  })

  it('shows the "Connected" badge for configured integration', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('integration-connected-badge')).toBeInTheDocument()
  })

  it('shows field count', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    // Fixture: field_count = 11
    expect(screen.getByText(/11 fields mapped/i)).toBeInTheDocument()
  })

  it('clicking "Details" expands the config', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)
    expect(screen.getByTestId('integration-details-airtable')).toBeInTheDocument()
  })

  it('expanded details shows api_key_env (env var name, not secret)', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)
    // Should show the env var NAME from the fixture
    const envDisplay = screen.getByTestId('integration-api-key-env')
    expect(envDisplay).toBeInTheDocument()
    expect(envDisplay.textContent).toBe('QUINTANA_AIRTABLE_API_KEY')
  })

  it('expanded details shows base_id and table_id', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)
    expect(screen.getByText('appw59LRBdv95UPpB')).toBeInTheDocument()
    expect(screen.getByText('tblsWumwwfeoqkWid')).toBeInTheDocument()
  })

  it('expanded details shows actionable field mapping UI', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)

    expect(screen.getByTestId('airtable-mapping-editor')).toBeInTheDocument()
    expect(screen.getByTestId('core-mappings-editor')).toBeInTheDocument()
    expect(screen.getByTestId('core-mapping-external_lead_id')).toBeInTheDocument()
    expect(screen.getByTestId('core-mapping-name')).toBeInTheDocument()
    expect(screen.getByTestId('core-mapping-phone')).toBeInTheDocument()
    expect(screen.getByTestId('core-mapping-email')).toBeInTheDocument()
    expect(screen.getByTestId('core-mapping-status')).toBeInTheDocument()
    expect(screen.getByTestId('custom-field-label-0')).toHaveValue('Car Make')
    expect(screen.getByTestId('quote-ready-selector')).toHaveTextContent('Car Make')
  })

  it('disables saving mappings when required core fields are empty', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/integrations', () =>
        HttpResponse.json([
          {
            provider: 'airtable',
            base_id: 'appw59LRBdv95UPpB',
            table_id: 'tblsWumwwfeoqkWid',
            api_key_env: 'QUINTANA_AIRTABLE_API_KEY',
            match_field: 'lead_id',
            field_count: 3,
            connected: true,
            field_mappings: [
              { source: 'external_lead_id', target: 'lead_id', type: 'integer' },
              { source: 'name', target: 'Nombre Completo', type: 'string' },
              { source: 'phone', target: 'Teléfono', type: 'phone' },
            ],
            field_definitions: [],
            quote_ready_fields: [],
          },
        ]),
      ),
    )

    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    expect(screen.getByTestId('save-mappings-button')).toBeDisabled()
    expect(screen.getByTestId('required-core-mappings-error')).toHaveTextContent(
      'Required mappings missing: email.',
    )
  })

  it('shows backend error detail when saving mappings fails', async () => {
    server.use(
      http.put('/api/v1/clients/:clientId/integrations/:provider/mappings', () =>
        HttpResponse.json(
          { detail: 'Missing required Airtable mappings: email.' },
          { status: 422 },
        ),
      ),
    )

    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))
    await waitFor(() => {
      expect(screen.getByTestId('save-mappings-button')).toBeEnabled()
    })
    await userEvent.click(screen.getByTestId('save-mappings-button'))

    await waitFor(() => {
      expect(screen.getByText(/missing required airtable mappings: email/i)).toBeInTheDocument()
    })
  })

  it('rejects non-snake_case custom field keys before saving', async () => {
    let putCalled = false
    server.use(
      http.put('/api/v1/clients/:clientId/integrations/:provider/mappings', () => {
        putCalled = true
        return HttpResponse.json({})
      }),
    )

    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    await userEvent.click(screen.getByTestId('add-custom-field-button'))
    const newIndex = 4
    // Single change event: the row's React key includes field_key, so per-keystroke
    // typing remounts the input and loses characters.
    fireEvent.change(screen.getByTestId(`custom-field-key-${newIndex}`), {
      target: { value: 'test-field' },
    })
    await userEvent.type(screen.getByTestId(`custom-field-label-${newIndex}`), 'Test Field')
    await userEvent.selectOptions(screen.getByTestId(`custom-field-target-${newIndex}`), 'lead_id')

    await waitFor(() => {
      expect(screen.getByTestId('save-mappings-button')).toBeEnabled()
    })
    await userEvent.click(screen.getByTestId('save-mappings-button'))

    await waitFor(() => {
      expect(screen.getByText(/keys must be snake_case/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/test-field/i)).toBeInTheDocument()
    expect(putCalled).toBe(false)
  })

  it('lets operator add and remove custom field rows', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    await userEvent.click(screen.getByTestId('add-custom-field-button'))
    const newIndex = 4
    expect(screen.getByTestId(`custom-field-key-${newIndex}`)).toBeInTheDocument()
    await userEvent.type(screen.getByTestId(`custom-field-key-${newIndex}`), 'policy_number')
    await userEvent.type(screen.getByTestId(`custom-field-label-${newIndex}`), 'Policy Number')
    await userEvent.selectOptions(screen.getByTestId(`custom-field-target-${newIndex}`), 'lead_id')

    expect(screen.getByTestId(`custom-field-label-${newIndex}`)).toHaveValue('Policy Number')
    await userEvent.click(screen.getByTestId(`remove-custom-field-${newIndex}`))
    expect(screen.queryByTestId(`custom-field-key-${newIndex}`)).not.toBeInTheDocument()
  })

  it('explains and updates quote-ready field selection', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    expect(screen.getByTestId('quote-ready-explanation')).toHaveTextContent(/must be present/i)
    const nameCheckbox = screen.getByTestId('quote-ready-name') as HTMLInputElement
    expect(nameCheckbox.checked).toBe(false)
    await userEvent.click(nameCheckbox)
    expect(nameCheckbox.checked).toBe(true)
  })

  it('does not render raw PAT values from integration config', async () => {
    server.use(
      http.get('/api/v1/clients/:clientId/integrations', () =>
        HttpResponse.json([
          {
            provider: 'airtable',
            base_id: 'appw59LRBdv95UPpB',
            table_id: 'tblsWumwwfeoqkWid',
            api_key_env: 'Stored credential (masked)',
            match_field: 'lead_id',
            field_count: 5,
            connected: true,
            field_mappings: [],
            field_definitions: [],
            quote_ready_fields: [],
          },
        ]),
      ),
    )

    const { container } = renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    expect(screen.getByTestId('integration-api-key-env')).toHaveTextContent('Stored credential (masked)')
    expect(container).not.toHaveTextContent(/pat[a-z0-9._-]+/i)
  })

  it('expanded details shows "Test Connection" button', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)
    expect(screen.getByTestId('test-connection-button')).toBeInTheDocument()
  })

  it('clicking "Test Connection" shows success toast with record count', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)

    const testBtn = screen.getByTestId('test-connection-button')
    await userEvent.click(testBtn)

    // MSW returns: "Connected. Found 42 records." — shown inline and in toast
    await waitFor(() => {
      expect(screen.getByTestId('test-result-inline')).toBeInTheDocument()
    })
    expect(screen.getByTestId('test-result-inline').textContent).toMatch(/found 42 records/i)
  })

  it('expanded details shows Disconnect button', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)
    expect(screen.getByTestId('disconnect-button')).toBeInTheDocument()
  })

  it('clicking Disconnect calls DELETE endpoint and shows success toast', async () => {
    renderIntegrationsSection('quintana-seguros')
    await waitFor(() => {
      expect(screen.queryByTestId('integrations-loading')).not.toBeInTheDocument()
    })
    const detailsBtn = screen.getByRole('button', { name: /details/i })
    await userEvent.click(detailsBtn)

    const disconnectBtn = screen.getByTestId('disconnect-button')
    await userEvent.click(disconnectBtn)

    // MSW returns { success: true, message: 'Integration disconnected' }
    await waitFor(() => {
      expect(screen.getByText(/integration disconnected/i)).toBeInTheDocument()
    })
  })
})
