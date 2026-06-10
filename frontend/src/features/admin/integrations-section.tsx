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
  useIntegrationFields,
  useSaveIntegrationMappings,
} from '@/api/hooks'
import type {
  ConnectIntegrationPayload,
  CRMFieldDefinition,
  CRMFieldMapping,
  IntegrationConfig,
} from '@/api/types'

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

const CORE_FIELDS = [
  { key: 'external_lead_id', label: 'External lead ID', type: 'integer' },
  { key: 'name', label: 'Name', type: 'string' },
  { key: 'phone', label: 'Phone', type: 'phone' },
  { key: 'email', label: 'Email', type: 'string' },
  { key: 'status', label: 'Status', type: 'string' },
] as const

const REQUIRED_CORE_FIELD_KEYS = ['external_lead_id', 'name', 'phone', 'email'] as const

const FIELD_TYPES = ['string', 'integer', 'boolean', 'date', 'phone'] as const

// Custom field keys become tool-schema property names and lead_custom_fields keys.
// Hyphens/uppercase break downstream lookups — enforce snake_case before saving.
const SNAKE_CASE_KEY_PATTERN = /^[a-z][a-z0-9_]*$/

function mappingTarget(config: IntegrationConfig, source: string): string {
  return config.field_mappings?.find((field) => field.source === source)?.target ?? ''
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
            Airtable API Key or Environment Variable
          </label>
          <input
            id={`api-key-env-${provider}`}
            type="password"
            value={apiKeyEnv}
            onChange={(e) => setApiKeyEnv(e.target.value)}
            placeholder="pat... or MY_CLIENT_AIRTABLE_API_KEY"
            required
            className="w-full text-sm font-mono px-3 py-2 rounded-md border border-line bg-white text-ink placeholder:text-ink-3 focus:outline-none focus:ring-2 focus:ring-teal focus:border-transparent"
            data-testid="connect-api-key-env-input"
          />
          <p className="text-[0.65rem] text-ink-3 mt-1">
            You can paste a PAT or an env var name. Qora stores it for use, but never displays the raw value again.
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
          <p className="text-[0.65rem] text-ink-3 mt-1">
            Airtable Base IDs start with <code>app</code>. Do not paste a shortened URL fragment.
          </p>
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
          <p className="text-[0.65rem] text-ink-3 mt-1">
            Prefer a Table ID that starts with <code>tbl</code>. Exact table names are also supported.
          </p>
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

interface MappingEditorProps {
  clientId: string
  config: IntegrationConfig
  onSuccess: (message: string) => void
  onError: (message: string) => void
}

function MappingEditor({ clientId, config, onSuccess, onError }: MappingEditorProps) {
  const fieldsQuery = useIntegrationFields(clientId, config.provider)
  const saveMutation = useSaveIntegrationMappings(clientId)
  const [coreMappings, setCoreMappings] = useState<Record<string, string>>(() =>
    Object.fromEntries(CORE_FIELDS.map((field) => [field.key, mappingTarget(config, field.key)])),
  )
  const [customFields, setCustomFields] = useState(() =>
    (config.field_definitions ?? []).map((field) => ({
      ...field,
      target: mappingTarget(config, field.field_key),
    })),
  )
  const [quoteReadyFields, setQuoteReadyFields] = useState<string[]>(config.quote_ready_fields ?? [])

  const airtableFields = fieldsQuery.data?.fields ?? []
  const missingRequiredCoreFields = REQUIRED_CORE_FIELD_KEYS.filter(
    (key) => !coreMappings[key]?.trim(),
  )
  const requiredCoreMappingMessage = missingRequiredCoreFields.length > 0
    ? `Required mappings missing: ${missingRequiredCoreFields.join(', ')}.`
    : null
  const configuredFieldKeys = [
    ...CORE_FIELDS.map((field) => ({ key: field.key, label: field.label })),
    ...customFields.map((field) => ({ key: field.field_key, label: field.label || field.field_key })),
  ]

  function setCustomField(index: number, patch: Partial<CRMFieldDefinition & { target: string }>) {
    setCustomFields((current) =>
      current.map((field, fieldIndex) => (fieldIndex === index ? { ...field, ...patch } : field)),
    )
  }

  function addCustomField() {
    setCustomFields((current) => [
      ...current,
      { field_key: '', label: '', field_type: 'string', required: false, target: '' },
    ])
  }

  function removeCustomField(index: number) {
    const removed = customFields[index]?.field_key
    setCustomFields((current) => current.filter((_, fieldIndex) => fieldIndex !== index))
    if (removed) {
      setQuoteReadyFields((current) => current.filter((field) => field !== removed))
    }
  }

  function toggleQuoteReady(fieldKey: string) {
    setQuoteReadyFields((current) =>
      current.includes(fieldKey)
        ? current.filter((field) => field !== fieldKey)
        : [...current, fieldKey],
    )
  }

  function handleSave() {
    if (missingRequiredCoreFields.length > 0) return

    const invalidCustomFieldKeys = customFields
      .map((field) => field.field_key.trim())
      .filter((key) => key && !SNAKE_CASE_KEY_PATTERN.test(key))
    if (invalidCustomFieldKeys.length > 0) {
      onError(
        `Invalid custom field keys: ${invalidCustomFieldKeys.join(', ')}. ` +
          "Keys must be snake_case (lowercase letters, digits, underscores; e.g. 'car_make').",
      )
      return
    }

    const coreFieldMappings: CRMFieldMapping[] = CORE_FIELDS
      .map((field) => ({ source: field.key, target: coreMappings[field.key] ?? '', type: field.type }))
      .filter((field) => field.target)

    const cleanedCustomFields = customFields
      .map((field) => ({
        field_key: field.field_key.trim(),
        label: field.label.trim(),
        field_type: field.field_type,
        required: quoteReadyFields.includes(field.field_key),
        target: field.target.trim(),
      }))
      .filter((field) => field.field_key && field.label && field.target)

    const customFieldMappings: CRMFieldMapping[] = cleanedCustomFields.map((field) => ({
      source: field.field_key,
      target: field.target,
      type: field.field_type,
      required: field.required,
    }))

    saveMutation.mutate(
      {
        provider: config.provider,
        payload: {
          field_mappings: [...coreFieldMappings, ...customFieldMappings],
          field_definitions: cleanedCustomFields.map(({ target: _target, ...field }) => field),
          quote_ready_fields: quoteReadyFields.filter((field) =>
            configuredFieldKeys.some((configured) => configured.key === field),
          ),
        },
      },
      {
        onSuccess: () => onSuccess('Airtable mappings saved.'),
        onError: (err) => onError(`Failed to save mappings: ${err.message}`),
      },
    )
  }

  return (
    <div className="space-y-4" data-testid="airtable-mapping-editor">
      <div className="rounded-lg border border-line bg-pearl p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-ink">Step 2: Map Airtable columns</p>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-ink-3">
              Choose which Airtable column feeds each Qora field. Quote-ready fields are the pieces of
              information that must be captured before a lead can be considered ready to quote or quoted.
            </p>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={
              saveMutation.isPending || fieldsQuery.isLoading || missingRequiredCoreFields.length > 0
            }
            data-testid="save-mappings-button"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save mappings'}
          </Button>
        </div>

        {fieldsQuery.isLoading && (
          <p className="mt-3 text-xs text-ink-3" data-testid="airtable-fields-loading">
            Loading Airtable columns…
          </p>
        )}
        {fieldsQuery.isError && (
          <p className="mt-3 rounded-md border border-coral-line bg-coral-faint px-3 py-2 text-xs text-coral" data-testid="airtable-fields-error">
            Could not load Airtable columns: {fieldsQuery.error.message}
          </p>
        )}
        {requiredCoreMappingMessage && (
          <p className="mt-3 rounded-md border border-coral-line bg-coral-faint px-3 py-2 text-xs text-coral" data-testid="required-core-mappings-error">
            {requiredCoreMappingMessage}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-lg border border-line bg-white p-4">
          <p className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-3">
            Core Mappings
          </p>
          <div className="space-y-3" data-testid="core-mappings-editor">
            {CORE_FIELDS.map((field) => (
              <label key={field.key} className="grid gap-1 sm:grid-cols-[160px_1fr] sm:items-center">
                <span className="text-xs font-medium text-ink">{field.label}</span>
                <select
                  value={coreMappings[field.key] ?? ''}
                  onChange={(event) =>
                    setCoreMappings((current) => ({ ...current, [field.key]: event.target.value }))
                  }
                  className="w-full rounded-md border border-line bg-pearl px-3 py-2 text-sm text-ink focus:border-transparent focus:outline-none focus:ring-2 focus:ring-teal"
                  data-testid={`core-mapping-${field.key}`}
                >
                  <option value="">Select Airtable column</option>
                  {airtableFields.map((airtableField) => (
                    <option key={airtableField.id ?? airtableField.name} value={airtableField.name}>
                      {airtableField.name}
                    </option>
                  ))}
                  {coreMappings[field.key] && !airtableFields.some((f) => f.name === coreMappings[field.key]) && (
                    <option value={coreMappings[field.key]}>{coreMappings[field.key]}</option>
                  )}
                </select>
              </label>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-line bg-white p-4">
          <p className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-3">
            Quote-Ready Fields
          </p>
          <p className="mb-3 text-xs leading-5 text-ink-3" data-testid="quote-ready-explanation">
            Select the fields that must be present before Qora treats the lead as quote-ready.
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-testid="quote-ready-selector">
            {configuredFieldKeys.map((field) => (
              <label key={field.key} className="flex items-center gap-2 rounded-md border border-line bg-pearl px-3 py-2 text-xs text-ink">
                <input
                  type="checkbox"
                  checked={quoteReadyFields.includes(field.key)}
                  onChange={() => toggleQuoteReady(field.key)}
                  data-testid={`quote-ready-${field.key}`}
                />
                {field.label}
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-line bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3">
            Custom Fields
          </p>
          <Button variant="secondary" size="sm" onClick={addCustomField} data-testid="add-custom-field-button">
            Add custom field
          </Button>
        </div>
        <div className="mt-3 space-y-3" data-testid="custom-fields-editor">
          {customFields.length === 0 && <p className="text-xs text-ink-3">No custom fields yet.</p>}
          {customFields.map((field, index) => (
            <div key={`${field.field_key}-${index}`} className="grid gap-2 rounded-md border border-line bg-pearl p-3 lg:grid-cols-[1fr_1fr_130px_1fr_auto] lg:items-end">
              <label className="space-y-1">
                <span className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3">Key</span>
                <input
                  value={field.field_key}
                  onChange={(event) => setCustomField(index, { field_key: event.target.value })}
                  placeholder="car_make"
                  className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink"
                  data-testid={`custom-field-key-${index}`}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3">Label</span>
                <input
                  value={field.label}
                  onChange={(event) => setCustomField(index, { label: event.target.value })}
                  placeholder="Car Make"
                  className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink"
                  data-testid={`custom-field-label-${index}`}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3">Type</span>
                <select
                  value={field.field_type}
                  onChange={(event) => setCustomField(index, { field_type: event.target.value as CRMFieldDefinition['field_type'] })}
                  className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink"
                  data-testid={`custom-field-type-${index}`}
                >
                  {FIELD_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-[0.65rem] font-semibold uppercase tracking-[0.08em] text-ink-3">Airtable Column</span>
                <select
                  value={field.target}
                  onChange={(event) => setCustomField(index, { target: event.target.value })}
                  className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink"
                  data-testid={`custom-field-target-${index}`}
                >
                  <option value="">Select column</option>
                  {airtableFields.map((airtableField) => (
                    <option key={airtableField.id ?? airtableField.name} value={airtableField.name}>
                      {airtableField.name}
                    </option>
                  ))}
                  {field.target && !airtableFields.some((f) => f.name === field.target) && (
                    <option value={field.target}>{field.target}</option>
                  )}
                </select>
              </label>
              <Button variant="secondary" size="sm" onClick={() => removeCustomField(index)} data-testid={`remove-custom-field-${index}`}>
                Remove
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
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

                  <MappingEditor
                    clientId={clientId}
                    config={config}
                    onSuccess={(msg) => showToast(msg, 'success')}
                    onError={(msg) => showToast(msg, 'error')}
                  />

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
