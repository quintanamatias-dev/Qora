/**
 * AgentsPanel — Agents tab content for admin panel
 *
 * Container-presentational: fetches data via hooks, delegates rendering.
 * Features:
 *  1. Client selector (active clients only)
 *  2. Agents table with actions (Edit, Default, Deactivate)
 *  3. Create Agent form
 *  4. Edit Agent inline panel
 */

import { useState } from 'react'
import {
  Card,
  Input,
  Button,
  Select,
  Textarea,
  Checkbox,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  Badge,
  Toast,
} from '@/design/components'
import {
  useClients,
  useAgents,
  useCreateAgent,
  useUpdateAgent,
  useDeactivateAgent,
  useMakeAgentDefault,
} from '@/api/hooks'
import type { Agent } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────────────────

const AVAILABLE_TOOLS = [
  'get_lead_details',
  'register_interest',
  'mark_not_interested',
  'schedule_followup',
]

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface ToastState {
  message: string
  status: 'success' | 'error'
}

// ──────────────────────────────────────────────────────────────────────────────
// AgentsPanel — container
// ──────────────────────────────────────────────────────────────────────────────

export function AgentsPanel() {
  const { data: clients } = useClients()
  const activeClients = (clients ?? []).filter((c) => c.is_active)

  const [selectedClientId, setSelectedClientId] = useState('')

  const { data: agents, isLoading: agentsLoading, isError: agentsError } = useAgents(selectedClientId)

  const createAgentMutation = useCreateAgent(selectedClientId)
  const updateAgentMutation = useUpdateAgent(selectedClientId)
  const deactivateAgentMutation = useDeactivateAgent(selectedClientId)
  const makeDefaultMutation = useMakeAgentDefault(selectedClientId)

  const [toast, setToast] = useState<ToastState | null>(null)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)

  // Create form state
  const [createForm, setCreateForm] = useState({
    slug: '',
    name: '',
    voice_id: '',
    model: 'gpt-4o',
    system_prompt: '',
    tools_enabled: [...AVAILABLE_TOOLS],
  })

  // Edit form state
  const [editForm, setEditForm] = useState({
    name: '',
    voice_id: '',
    system_prompt: '',
    tools_enabled: [...AVAILABLE_TOOLS],
  })

  function showToast(message: string, status: 'success' | 'error') {
    setToast({ message, status })
  }

  // ── Tool toggle helpers ────────────────────────────────────────────────────

  function toggleCreateTool(tool: string) {
    setCreateForm((f) => ({
      ...f,
      tools_enabled: f.tools_enabled.includes(tool)
        ? f.tools_enabled.filter((t) => t !== tool)
        : [...f.tools_enabled, tool],
    }))
  }

  function toggleEditTool(tool: string) {
    setEditForm((f) => ({
      ...f,
      tools_enabled: f.tools_enabled.includes(tool)
        ? f.tools_enabled.filter((t) => t !== tool)
        : [...f.tools_enabled, tool],
    }))
  }

  // ── Create Agent ───────────────────────────────────────────────────────────

  function handleCreateSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedClientId || !createForm.slug.trim() || !createForm.name.trim()) return

    createAgentMutation.mutate(
      {
        slug: createForm.slug.trim(),
        name: createForm.name.trim(),
        voice_id: createForm.voice_id.trim(),
        model: createForm.model.trim() || 'gpt-4o',
        system_prompt: createForm.system_prompt.trim() || null,
        tools_enabled: createForm.tools_enabled,
      },
      {
        onSuccess: () => {
          showToast('Agent created successfully', 'success')
          setCreateForm({
            slug: '',
            name: '',
            voice_id: '',
            model: 'gpt-4o',
            system_prompt: '',
            tools_enabled: [...AVAILABLE_TOOLS],
          })
        },
        onError: (err) => {
          showToast(`Error creating agent: ${err.message}`, 'error')
        },
      },
    )
  }

  // ── Edit Agent ─────────────────────────────────────────────────────────────

  function handleEditClick(agent: Agent) {
    setEditingAgent(agent)
    setEditForm({
      name: agent.name,
      voice_id: agent.voice_id,
      system_prompt: agent.system_prompt ?? '',
      tools_enabled: [...agent.tools_enabled],
    })
  }

  function handleEditCancel() {
    setEditingAgent(null)
  }

  function handleEditSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!editingAgent) return

    updateAgentMutation.mutate(
      {
        agentId: editingAgent.agent_id,
        payload: {
          name: editForm.name || undefined,
          voice_id: editForm.voice_id || undefined,
          system_prompt: editForm.system_prompt || null,
          tools_enabled: editForm.tools_enabled,
        },
      },
      {
        onSuccess: () => {
          showToast('Agent updated successfully', 'success')
          setEditingAgent(null)
        },
        onError: (err) => {
          showToast(`Error updating agent: ${err.message}`, 'error')
        },
      },
    )
  }

  // ── Deactivate Agent ───────────────────────────────────────────────────────

  function handleDeactivate(agentId: string) {
    deactivateAgentMutation.mutate(agentId, {
      onSuccess: () => showToast('Agent deactivated', 'success'),
      onError: (err) => showToast(`Error deactivating agent: ${err.message}`, 'error'),
    })
  }

  // ── Make Default ───────────────────────────────────────────────────────────

  function handleMakeDefault(agentId: string) {
    makeDefaultMutation.mutate(agentId, {
      onSuccess: () => showToast('Agent set as default', 'success'),
      onError: (err) => showToast(`Error setting default agent: ${err.message}`, 'error'),
    })
  }

  return (
    <div className="space-y-6">
      {/* Toast notification */}
      {toast && (
        <Toast
          message={toast.message}
          status={toast.status}
          onDismiss={() => setToast(null)}
        />
      )}

      {/* Client selector */}
      <Card>
        <h2 className="font-display text-base font-semibold text-on-surface mb-4">
          Select Client
        </h2>
        <div className="max-w-xs">
          <Select
            label="Client"
            value={selectedClientId}
            onChange={(e) => {
              setSelectedClientId(e.target.value)
              setEditingAgent(null)
            }}
          >
            <option value="">— Choose a client —</option>
            {activeClients.map((client) => (
              <option key={client.client_id} value={client.client_id}>
                {client.broker_name} ({client.client_id})
              </option>
            ))}
          </Select>
        </div>
      </Card>

      {/* Agents section — only shown when client selected */}
      {selectedClientId && (
        <>
          {/* Edit Agent inline panel */}
          {editingAgent && (
            <Card stripe>
              <h2 className="font-display text-base font-semibold text-on-surface mb-4">
                Edit Agent: <code className="text-primary font-mono text-sm">{editingAgent.slug}</code>
              </h2>
              <form onSubmit={handleEditSubmit} className="space-y-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Input
                    label="Name"
                    value={editForm.name}
                    onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                  />
                  <Input
                    label="Voice ID"
                    value={editForm.voice_id}
                    onChange={(e) => setEditForm((f) => ({ ...f, voice_id: e.target.value }))}
                  />
                </div>
                <Textarea
                  label="System Prompt"
                  value={editForm.system_prompt}
                  onChange={(e) => setEditForm((f) => ({ ...f, system_prompt: e.target.value }))}
                  minRows={4}
                  placeholder="System prompt for the agent…"
                />
                <div>
                  <p className="text-xs font-medium uppercase tracking-widest text-on-surface-variant mb-2">
                    Tools Enabled
                  </p>
                  <div className="flex flex-wrap gap-4">
                    {AVAILABLE_TOOLS.map((tool) => (
                      <Checkbox
                        key={tool}
                        label={tool}
                        checked={editForm.tools_enabled.includes(tool)}
                        onChange={() => toggleEditTool(tool)}
                      />
                    ))}
                  </div>
                </div>
                <div className="flex gap-2 justify-end">
                  <Button type="button" variant="tertiary" size="sm" onClick={handleEditCancel}>
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    variant="primary"
                    size="sm"
                    disabled={updateAgentMutation.isPending}
                  >
                    {updateAgentMutation.isPending ? 'Saving…' : 'Save'}
                  </Button>
                </div>
              </form>
            </Card>
          )}

          {/* Agents table */}
          <Card>
            <h2 className="font-display text-base font-semibold text-on-surface mb-4">
              Agents for <code className="text-primary font-mono text-sm">{selectedClientId}</code>
            </h2>

            {agentsLoading && (
              <div data-testid="agents-loading" className="space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-10 bg-surface-container rounded-sm animate-pulse" />
                ))}
              </div>
            )}

            {agentsError && (
              <div data-testid="agents-error" role="alert" className="py-8 text-center">
                <p className="text-on-surface font-medium">Unable to load agents. Please try again.</p>
              </div>
            )}

            {!agentsLoading && !agentsError && agents && agents.length === 0 && (
              <div data-testid="agents-empty" className="py-8 text-center">
                <p className="text-on-surface font-medium">No agents found</p>
                <p className="text-on-surface-variant text-sm mt-1">Create the first agent below.</p>
              </div>
            )}

            {!agentsLoading && !agentsError && agents && agents.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Slug</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Voice ID</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {agents.map((agent) => (
                    <TableRow key={agent.agent_id}>
                      <TableCell>
                        <code className="font-mono text-xs text-primary">{agent.slug}</code>
                      </TableCell>
                      <TableCell>{agent.name}</TableCell>
                      <TableCell>
                        <code className="font-mono text-xs text-on-surface-variant">{agent.voice_id}</code>
                      </TableCell>
                      <TableCell>
                        <code className="font-mono text-xs text-on-surface-variant">{agent.model}</code>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1 flex-wrap">
                          <Badge status={agent.is_active ? 'active' : 'neutral'}>
                            {agent.is_active ? 'Active' : 'Inactive'}
                          </Badge>
                          {agent.is_default && (
                            <Badge status="success">Default</Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-2 flex-wrap">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handleEditClick(agent)}
                          >
                            Edit
                          </Button>
                          {!agent.is_default && (
                            <Button
                              variant="tertiary"
                              size="sm"
                              onClick={() => handleMakeDefault(agent.agent_id)}
                              disabled={makeDefaultMutation.isPending}
                            >
                              ★ Default
                            </Button>
                          )}
                          {agent.is_active && (
                            <Button
                              variant="tertiary"
                              size="sm"
                              className="text-error hover:text-error"
                              onClick={() => handleDeactivate(agent.agent_id)}
                              disabled={deactivateAgentMutation.isPending}
                            >
                              Deactivate
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>

          {/* Create Agent form */}
          <Card>
            <h2 className="font-display text-base font-semibold text-on-surface mb-4">
              Create Agent
            </h2>
            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Input
                  label="Slug"
                  placeholder="my-agent"
                  value={createForm.slug}
                  onChange={(e) => setCreateForm((f) => ({ ...f, slug: e.target.value }))}
                  required
                />
                <Input
                  label="Name"
                  placeholder="My Agent"
                  value={createForm.name}
                  onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
                  required
                />
                <Input
                  label="Voice ID"
                  placeholder="voice-abc"
                  value={createForm.voice_id}
                  onChange={(e) => setCreateForm((f) => ({ ...f, voice_id: e.target.value }))}
                  required
                />
                <Input
                  label="Model"
                  placeholder="gpt-4o"
                  value={createForm.model}
                  onChange={(e) => setCreateForm((f) => ({ ...f, model: e.target.value }))}
                />
              </div>
              <Textarea
                label="System Prompt"
                value={createForm.system_prompt}
                onChange={(e) => setCreateForm((f) => ({ ...f, system_prompt: e.target.value }))}
                minRows={4}
                placeholder="System prompt for the agent…"
              />
              <div>
                <p className="text-xs font-medium uppercase tracking-widest text-on-surface-variant mb-2">
                  Tools Enabled
                </p>
                <div className="flex flex-wrap gap-4">
                  {AVAILABLE_TOOLS.map((tool) => (
                    <Checkbox
                      key={tool}
                      label={tool}
                      checked={createForm.tools_enabled.includes(tool)}
                      onChange={() => toggleCreateTool(tool)}
                    />
                  ))}
                </div>
              </div>
              <div className="flex justify-end">
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={createAgentMutation.isPending}
                >
                  {createAgentMutation.isPending ? 'Creating…' : 'Create Agent'}
                </Button>
              </div>
            </form>
          </Card>
        </>
      )}
    </div>
  )
}
