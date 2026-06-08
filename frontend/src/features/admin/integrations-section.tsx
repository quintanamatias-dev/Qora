/**
 * IntegrationsSection — CRM integration configuration section
 *
 * Shows all supported integration providers with their connection status.
 * Uses useAvailableIntegrations(clientId) as the primary query.
 *
 * States per provider:
 *  - is_connected === true  → connected card with config details, test connection, disconnect
 *  - is_connected === false → "Connect" card with expandable form
 *
 * Global states:
 *  - Loading: skeleton/spinner
 *  - Error: clean error state with retry
 */

import { useState } from 'react'
import { Button, Card, Toast } from '@/design/components'
import {
  useAvailableIntegrations,
  useIntegrations,
  useTestIntegration,
  useConnectIntegration,
  useDisconnectIntegration,
} from '@/api/hooks'
import type { ConnectIntegrationPayload } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface ToastState {
  message: string
  status: 'success' | 'error'
}

interface IntegrationsSectionProps {
  clientId: string
}

// ──────────────────────────────────────────────────────────────────────────────
// ConnectForm — expandable form for a not-yet-connected provider
// ──────────────────────────────────────────────────────────────────────────────

interface ConnectFormProps {
  provider: string
  clientId: string
  onSuccess: (message: string) => void
  onError: (message: string) => void
}

function ConnectForm({ provider, clientId, onSuccess, onError }: ConnectFormProps) {
  const [apiKeyEnv, setApiKeyEnv] = useState('')
  const [baseId, setBaseId] = useState('')
  const [tableId, setTableId] = useState('')

  const connectMutation = useConnectIntegration(clientId)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const payload: ConnectIntegrationPayload = {
      base_id: baseId.trim(),
      table_id: tableId.trim(),
      api_key_env: apiKeyEnv.trim(),
    }
    connectMutation.mutate(
      { provider, payload },
      {
        onSuccess: () => {
          onSuccess(`${provider} integration connected successfully.`)
        },
        onError: (err) => {
          onError(`Failed to connect: ${err.message}`)
        },
      },
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      data-testid={`connect-form-${provider}`}
      className="mt-4 pt-4 border-t border-line space-y-4"
    >
      <div className="space-y-3">
        {/* API Key Env Var */}
        <div>
          <label
            htmlFor={`api-key-env-${provider}`}
            className="block text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1"
          >
            API Key Environment Variable
          </label>
          <input
            id={`api-key-env-${provider}`}
            type="text"
            value={apiKeyEnv}
            onChange={(e) => setApiKeyEnv(e.target.value)}
            placeholder="MY_CLIENT_AIRTABLE_API_KEY"
            required
            className="w-full text-sm font-mono px-3 py-2 rounded-md border border-line bg-white text-ink placeholder:text-ink-3 focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent"
            data-testid="connect-api-key-env-input"
          />
          <p className="text-[0.65rem] text-ink-3 mt-1">
            Environment variable name for your Airtable API key (e.g., MY_CLIENT_AIRTABLE_API_KEY).
            The actual API key value is never entered here.
          </p>
        </div>

        {/* Base ID */}
        <div>
          <label
            htmlFor={`base-id-${provider}`}
            className="block text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1"
          >
            Base ID
          </label>
          <input
            id={`base-id-${provider}`}
            type="text"
            value={baseId}
            onChange={(e) => setBaseId(e.target.value)}
            placeholder="appXXXXXXXXXXXX"
            required
            className="w-full text-sm font-mono px-3 py-2 rounded-md border border-line bg-white text-ink placeholder:text-ink-3 focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent"
            data-testid="connect-base-id-input"
          />
        </div>

        {/* Table ID */}
        <div>
          <label
            htmlFor={`table-id-${provider}`}
            className="block text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1"
          >
            Table ID
          </label>
          <input
            id={`table-id-${provider}`}
            type="text"
            value={tableId}
            onChange={(e) => setTableId(e.target.value)}
            placeholder="tblXXXXXXXXXXXX"
            required
            className="w-full text-sm font-mono px-3 py-2 rounded-md border border-line bg-white text-ink placeholder:text-ink-3 focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent"
            data-testid="connect-table-id-input"
          />
        </div>
      </div>

      <div className="flex justify-end pt-1">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={connectMutation.isPending}
          data-testid={`connect-submit-${provider}`}
        >
          {connectMutation.isPending ? 'Connecting…' : 'Connect'}
        </Button>
      </div>
    </form>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// IntegrationsSection — container
// ──────────────────────────────────────────────────────────────────────────────

export function IntegrationsSection({ clientId }: IntegrationsSectionProps) {
  const {
    data: availableIntegrations,
    isLoading,
    isError,
    refetch,
  } = useAvailableIntegrations(clientId)

  // Also fetch the full config for connected integrations (details view)
  const { data: connectedIntegrations } = useIntegrations(clientId)

  const testMutation = useTestIntegration(clientId)
  const disconnectMutation = useDisconnectIntegration(clientId)

  const [toast, setToast] = useState<ToastState | null>(null)
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null)
  const [connectFormProvider, setConnectFormProvider] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{
    provider: string
    success: boolean
    message: string
  } | null>(null)

  function showToast(message: string, status: 'success' | 'error') {
    setToast({ message, status })
  }

  function handleTestConnection(provider: string) {
    setTestResult(null)
    testMutation.mutate(provider, {
      onSuccess: (result) => {
        setTestResult({ provider, success: result.success, message: result.message })
        showToast(result.message, result.success ? 'success' : 'error')
      },
      onError: (err) => {
        setTestResult({ provider, success: false, message: err.message })
        showToast(`Connection test failed: ${err.message}`, 'error')
      },
    })
  }

  function handleDisconnect(provider: string) {
    disconnectMutation.mutate(provider, {
      onSuccess: (result) => {
        setExpandedProvider(null)
        showToast(result.message, 'success')
      },
      onError: (err) => {
        showToast(`Failed to disconnect: ${err.message}`, 'error')
      },
    })
  }

  // ── Loading ────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div data-testid="integrations-loading" className="space-y-2 pt-2">
        <div className="h-10 bg-mist rounded-md animate-pulse" />
        <div className="h-10 bg-mist rounded-md animate-pulse" />
      </div>
    )
  }

  // ── Error ──────────────────────────────────────────────────────────────────

  if (isError) {
    return (
      <div data-testid="integrations-error" className="py-8 text-center pt-2">
        <p className="text-ink font-medium">Unable to load integrations.</p>
        <Button
          variant="secondary"
          size="sm"
          className="mt-3"
          onClick={() => void refetch()}
        >
          Retry
        </Button>
      </div>
    )
  }

  // ── Empty (no available integrations at all — shouldn't happen in practice) ──

  if (!availableIntegrations || availableIntegrations.length === 0) {
    return (
      <div data-testid="integrations-empty" className="py-8 text-center pt-2">
        <div className="text-3xl mb-3 text-ink-4" aria-hidden="true">⚡</div>
        <p className="text-ink font-medium">No integrations configured</p>
        <p className="text-sm text-ink-3 mt-1">
          Configure a CRM integration to sync leads automatically.
        </p>
      </div>
    )
  }

  // ── Available integrations list ────────────────────────────────────────────

  // Determine if any integration is connected (for "integrations-list" vs "integrations-empty" testids)
  const hasConnected = availableIntegrations.some((i) => i.is_connected)

  return (
    <div
      data-testid={hasConnected ? 'integrations-list' : 'integrations-available'}
      className="space-y-4 pt-2"
    >
      {/* Toast notification */}
      {toast && (
        <Toast
          message={toast.message}
          status={toast.status}
          onDismiss={() => setToast(null)}
        />
      )}

      {availableIntegrations.map((available) => {
        const config = connectedIntegrations?.find((c) => c.provider === available.provider)

        if (available.is_connected && config) {
          // ── Connected card ─────────────────────────────────────────────────
          return (
            <Card key={available.provider}>
              {/* Integration header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {/* Provider logo */}
                  <div className="w-8 h-8 rounded-md overflow-hidden flex-shrink-0">
                    {available.provider === 'airtable' ? (
                      <img
                        src="/images/integrations/airtable-icon.webp"
                        alt="Airtable"
                        width={32}
                        height={32}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <span className="text-teal text-xs font-mono font-bold uppercase">
                        {available.provider.slice(0, 2)}
                      </span>
                    )}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink capitalize">{available.provider}</span>
                      {config.connected && (
                        <span
                          className="text-[10px] font-mono font-semibold uppercase tracking-[0.15em] text-teal bg-teal-faint border border-teal-line px-2 py-0.5 rounded-full"
                          data-testid="integration-connected-badge"
                        >
                          Connected
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-ink-3 mt-0.5">
                      {config.field_count} fields mapped
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setExpandedProvider(
                      expandedProvider === available.provider ? null : available.provider,
                    )
                  }
                  className="text-ink-3 hover:text-ink transition-colors text-sm px-2 py-1"
                  aria-expanded={expandedProvider === available.provider}
                >
                  {expandedProvider === available.provider ? 'Hide ▲' : 'Details ▾'}
                </button>
              </div>

              {/* Expandable config details */}
              {expandedProvider === available.provider && (
                <div
                  data-testid={`integration-details-${available.provider}`}
                  className="mt-4 pt-4 border-t border-line space-y-3"
                >
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <p className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1">
                        Base ID
                      </p>
                      <code className="text-xs font-mono text-ink">{config.base_id}</code>
                    </div>
                    <div>
                      <p className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1">
                        Table ID
                      </p>
                      <code className="text-xs font-mono text-ink">{config.table_id}</code>
                    </div>
                    <div>
                      <p className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1">
                        API Key Env
                      </p>
                      <code
                        className="text-xs font-mono text-ink"
                        data-testid="integration-api-key-env"
                      >
                        {config.api_key_env}
                      </code>
                    </div>
                    <div>
                      <p className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1">
                        Match Field
                      </p>
                      <code className="text-xs font-mono text-ink">{config.match_field}</code>
                    </div>
                  </div>

                  {/* Inline test result feedback */}
                  {testResult && testResult.provider === available.provider && (
                    <div
                      data-testid="test-result-inline"
                      className={[
                        'flex items-center gap-2 px-3 py-2 rounded-md text-sm',
                        testResult.success
                          ? 'bg-teal-faint text-teal border border-teal-line'
                          : 'bg-coral-faint text-coral border border-coral-line',
                      ].join(' ')}
                    >
                      <span
                        className={`w-2 h-2 rounded-full flex-shrink-0 ${
                          testResult.success ? 'bg-teal' : 'bg-coral'
                        }`}
                      />
                      {testResult.message}
                    </div>
                  )}

                  <div className="flex items-center justify-between pt-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleDisconnect(available.provider)}
                      disabled={disconnectMutation.isPending}
                      className="text-coral hover:text-coral border-coral-line hover:border-coral"
                      data-testid="disconnect-button"
                    >
                      {disconnectMutation.isPending ? 'Disconnecting…' : 'Disconnect'}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleTestConnection(available.provider)}
                      disabled={testMutation.isPending}
                      data-testid="test-connection-button"
                    >
                      {testMutation.isPending ? 'Testing…' : 'Test Connection'}
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          )
        }

        // ── Not-connected card ───────────────────────────────────────────────
        const isFormOpen = connectFormProvider === available.provider

        return (
          <Card key={available.provider}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {/* Provider logo */}
                <div className="w-8 h-8 rounded-md overflow-hidden flex-shrink-0 flex items-center justify-center bg-mist">
                  {available.icon ? (
                    <img
                      src={available.icon}
                      alt={available.name}
                      width={32}
                      height={32}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <span className="text-ink-3 text-xs font-mono font-bold uppercase">
                      {available.provider.slice(0, 2)}
                    </span>
                  )}
                </div>
                <div>
                  <span className="font-medium text-ink">{available.name}</span>
                  <p className="text-xs text-ink-3 mt-0.5">{available.description}</p>
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  setConnectFormProvider(isFormOpen ? null : available.provider)
                }
                data-testid={`connect-button-${available.provider}`}
              >
                {isFormOpen ? 'Cancel' : 'Connect'}
              </Button>
            </div>

            {/* Expandable connect form */}
            {isFormOpen && (
              <ConnectForm
                provider={available.provider}
                clientId={clientId}
                onSuccess={(msg) => {
                  setConnectFormProvider(null)
                  showToast(msg, 'success')
                }}
                onError={(msg) => showToast(msg, 'error')}
              />
            )}
          </Card>
        )
      })}
    </div>
  )
}
