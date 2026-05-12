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
import type { Agent, ReadinessCheck } from '@/api/types'

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
// Pure helpers (exported for unit tests)
// ──────────────────────────────────────────────────────────────────────────────

/**
 * computeReadinessChecklist — derives per-item readiness from AgentResponse fields.
 *
 * Pure function: no side effects, deterministic from agent data.
 * Spec: has_prompt, has_elevenlabs_agent_id, custom_llm_url presence.
 */
export function computeReadinessChecklist(agent: Agent): ReadinessCheck[] {
  return [
    {
      label: 'System prompt configured',
      ready: agent.has_prompt,
    },
    {
      label: 'ElevenLabs agent ID bound',
      ready: agent.has_elevenlabs_agent_id,
    },
    {
      label: 'Custom LLM URL available',
      ready: Boolean(agent.custom_llm_url),
    },
  ]
}

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
    tts_speed: 0.95,
    tts_stability: 0.4,
    tts_similarity_boost: 0.75,
  })

  // Edit form state
  const [editForm, setEditForm] = useState({
    name: '',
    voice_id: '',
    system_prompt: '',
    tools_enabled: [...AVAILABLE_TOOLS],
    elevenlabs_agent_id: '',
    knowledge_base: '',
    temperature: 0.7,
    max_tokens: 512,
    tts_speed: 0.95,
    tts_stability: 0.4,
    tts_similarity_boost: 0.75,
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
        tts_speed: createForm.tts_speed,
        tts_stability: createForm.tts_stability,
        tts_similarity_boost: createForm.tts_similarity_boost,
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
            tts_speed: 0.95,
            tts_stability: 0.4,
            tts_similarity_boost: 0.75,
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
      elevenlabs_agent_id: agent.elevenlabs_agent_id ?? '',
      knowledge_base: agent.knowledge_base ?? '',
      temperature: agent.temperature ?? 0.7,
      max_tokens: agent.max_tokens ?? 512,
      tts_speed: agent.tts_speed ?? 0.95,
      tts_stability: agent.tts_stability ?? 0.4,
      tts_similarity_boost: agent.tts_similarity_boost ?? 0.75,
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
          elevenlabs_agent_id: editForm.elevenlabs_agent_id || null,
          knowledge_base: editForm.knowledge_base || null,
          temperature: editForm.temperature,
          max_tokens: editForm.max_tokens,
          tts_speed: editForm.tts_speed,
          tts_stability: editForm.tts_stability,
          tts_similarity_boost: editForm.tts_similarity_boost,
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
        <div className="mb-4">
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
            Select Client
          </p>
        </div>
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
              <div className="mb-4">
                <p className="text-[0.72rem] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
                  Edit Agent
                </p>
                <code className="text-primary font-mono text-xs mt-0.5 block">{editingAgent.slug}</code>
              </div>

              {/* Readiness Checklist */}
              <div className="mb-6 p-4 rounded-md border border-surface-container-high bg-surface-container/50">
                <p className="text-xs font-medium uppercase tracking-widest text-on-surface-variant mb-3">
                  Readiness
                </p>
                {/* Overall readiness indicator */}
                <p
                  className={`text-sm font-medium mb-3 ${
                    editingAgent.is_conversation_ready ? 'text-success' : 'text-warning'
                  }`}
                >
                  {editingAgent.is_conversation_ready
                    ? '✓ Ready for conversation'
                    : '✗ Not ready for conversation'}
                </p>
                <ul className="space-y-1.5">
                  {computeReadinessChecklist(editingAgent).map((check) => (
                    <li key={check.label} className="flex items-center gap-2 text-sm">
                      <span
                        aria-hidden="true"
                        className={check.ready ? 'text-success' : 'text-warning'}
                      >
                        {check.ready ? '✓' : '✗'}
                      </span>
                      <span className={check.ready ? 'text-on-surface' : 'text-on-surface-variant'}>
                        {check.label}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Custom LLM URL — read-only with copy */}
              <div className="mb-4">
                <p className="text-xs font-medium uppercase tracking-widest text-on-surface-variant mb-1.5">
                  Custom LLM URL
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs font-mono text-primary bg-surface-container px-3 py-2 rounded-sm truncate">
                    {editingAgent.custom_llm_url}
                  </code>
                  <Button
                    type="button"
                    variant="tertiary"
                    size="sm"
                    onClick={() => {
                      void navigator.clipboard.writeText(editingAgent.custom_llm_url)
                      showToast('Custom LLM URL copied', 'success')
                    }}
                  >
                    Copy
                  </Button>
                </div>
                <p className="text-xs text-on-surface-variant mt-1">
                  Paste this URL into the ElevenLabs dashboard as the Custom LLM endpoint.
                </p>
              </div>

              <form onSubmit={handleEditSubmit} className="space-y-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Input
                    label="Name"
                    value={editForm.name}
                    onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                  />
                  <div>
                    <Input
                      label="Voice ID"
                      value={editForm.voice_id}
                      onChange={(e) => setEditForm((f) => ({ ...f, voice_id: e.target.value }))}
                    />
                    <p className="text-xs text-on-surface-variant mt-1">
                      Voice for ElevenLabs conversational agents is configured in the{' '}
                      <span className="font-medium">ElevenLabs dashboard</span>, not here.
                    </p>
                  </div>
                </div>

                <Input
                  label="ElevenLabs Agent ID"
                  value={editForm.elevenlabs_agent_id}
                  onChange={(e) => setEditForm((f) => ({ ...f, elevenlabs_agent_id: e.target.value }))}
                  placeholder="el_xxxxxxxxxxxxxx"
                />

                <Textarea
                  label="System Prompt"
                  value={editForm.system_prompt}
                  onChange={(e) => setEditForm((f) => ({ ...f, system_prompt: e.target.value }))}
                  minRows={4}
                  placeholder="System prompt for the agent…"
                />

                <Textarea
                  label="Knowledge Base"
                  value={editForm.knowledge_base}
                  onChange={(e) => setEditForm((f) => ({ ...f, knowledge_base: e.target.value }))}
                  minRows={3}
                  placeholder="Knowledge base content…"
                />

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Input
                    label="Temperature"
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={String(editForm.temperature)}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, temperature: parseFloat(e.target.value) || 0.7 }))
                    }
                  />
                  <Input
                    label="Max Tokens"
                    type="number"
                    min={1}
                    max={8192}
                    step={1}
                    value={String(editForm.max_tokens)}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, max_tokens: parseInt(e.target.value, 10) || 512 }))
                    }
                  />
                </div>

                <div>
                  <p className="text-xs font-medium uppercase tracking-widest text-on-surface-variant mb-2">
                    Voice Tuning
                  </p>
                  <p className="text-xs text-on-surface-variant mb-3">
                    Adjust how the voice sounds during live calls. Changes take effect on the next call.
                  </p>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    <div>
                      <Input
                        label="Speed"
                        type="number"
                        min={0.7}
                        max={1.2}
                        step={0.05}
                        value={String(editForm.tts_speed)}
                        onChange={(e) =>
                          setEditForm((f) => ({ ...f, tts_speed: parseFloat(e.target.value) || 0.95 }))
                        }
                      />
                      <p className="text-xs text-on-surface-variant mt-1">EL range: 0.7 – 1.2</p>
                    </div>
                    <Input
                      label="Stability"
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={String(editForm.tts_stability)}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, tts_stability: parseFloat(e.target.value) || 0.4 }))
                      }
                    />
                    <Input
                      label="Similarity boost"
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={String(editForm.tts_similarity_boost)}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, tts_similarity_boost: parseFloat(e.target.value) || 0.75 }))
                      }
                    />
                  </div>
                </div>

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
            <div className="flex items-center justify-between mb-4">
              <p className="text-[0.72rem] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
                Agents
              </p>
              <code className="font-mono text-xs text-primary">{selectedClientId}</code>
            </div>

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
                    <TableHead>Voice Tuning</TableHead>
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
                        <div className="text-xs text-on-surface-variant space-y-0.5" data-testid={`voice-tuning-${agent.agent_id}`}>
                          <div>Speed: <span className="font-medium text-on-surface">{agent.tts_speed}</span></div>
                          <div>Stability: <span className="font-medium text-on-surface">{agent.tts_stability}</span></div>
                          <div>Similarity: <span className="font-medium text-on-surface">{agent.tts_similarity_boost}</span></div>
                        </div>
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
            <div className="mb-4">
              <p className="text-[0.72rem] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
                New Agent
              </p>
            </div>
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
                  Voice Tuning
                </p>
                <p className="text-xs text-on-surface-variant mb-3">
                  How the voice sounds during live calls. Defaults work well for most agents.
                </p>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <div>
                    <Input
                      label="Speed"
                      type="number"
                      min={0.7}
                      max={1.2}
                      step={0.05}
                      value={String(createForm.tts_speed)}
                      onChange={(e) =>
                        setCreateForm((f) => ({ ...f, tts_speed: parseFloat(e.target.value) || 0.95 }))
                      }
                    />
                    <p className="text-xs text-on-surface-variant mt-1">EL range: 0.7 – 1.2</p>
                  </div>
                  <Input
                    label="Stability"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={String(createForm.tts_stability)}
                    onChange={(e) =>
                      setCreateForm((f) => ({ ...f, tts_stability: parseFloat(e.target.value) || 0.4 }))
                    }
                  />
                  <Input
                    label="Similarity boost"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={String(createForm.tts_similarity_boost)}
                    onChange={(e) =>
                      setCreateForm((f) => ({ ...f, tts_similarity_boost: parseFloat(e.target.value) || 0.75 }))
                    }
                  />
                </div>
              </div>
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
