/**
 * AdminClientsListPage — Admin entry page: client list with drill-down
 *
 * Replaces the old flat tab layout.
 * Features:
 *  1. "Clients" heading with subtitle
 *  2. Create Client form
 *  3. Clickable client table — each row navigates to /admin/clients/:clientId
 *  4. Inline edit and deactivate actions
 */

import { useState } from 'react'
import { useNavigate } from 'react-router'
import {
  Card,
  Input,
  Button,
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
  useCreateClient,
  useUpdateClient,
  useDeactivateClient,
} from '@/api/hooks'
import type { Client } from '@/api/types'

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface ToastState {
  message: string
  status: 'success' | 'error'
}

// ──────────────────────────────────────────────────────────────────────────────
// AdminClientsListPage — container
// ──────────────────────────────────────────────────────────────────────────────

export function AdminPage() {
  const navigate = useNavigate()
  const { data: clients, isLoading, isError } = useClients()
  const createClientMutation = useCreateClient()
  const updateClientMutation = useUpdateClient()
  const deactivateClientMutation = useDeactivateClient()

  const [toast, setToast] = useState<ToastState | null>(null)
  const [editingClient, setEditingClient] = useState<Client | null>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)

  // Create form state
  const [createForm, setCreateForm] = useState({
    client_id: '',
    name: '',
    agent_name: 'Jaumpablo',
  })

  // Edit form state
  const [editForm, setEditForm] = useState({
    name: '',
    agent_name: '',
    voice_id: '',
  })

  function showToast(message: string, status: 'success' | 'error') {
    setToast({ message, status })
  }

  // ── Create Client ──────────────────────────────────────────────────────────

  function handleCreateSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!createForm.client_id.trim() || !createForm.name.trim()) return

    createClientMutation.mutate(
      {
        client_id: createForm.client_id.trim(),
        name: createForm.name.trim(),
        agent_name: createForm.agent_name.trim() || 'Jaumpablo',
      },
      {
        onSuccess: () => {
          showToast('Client created successfully', 'success')
          setCreateForm({ client_id: '', name: '', agent_name: 'Jaumpablo' })
          setShowCreateForm(false)
        },
        onError: (err) => {
          showToast(`Error creating client: ${err.message}`, 'error')
        },
      },
    )
  }

  // ── Edit Client ────────────────────────────────────────────────────────────

  function handleEditClick(e: React.MouseEvent, client: Client) {
    e.stopPropagation() // prevent row click from navigating
    setEditingClient(client)
    setEditForm({
      name: client.name,
      agent_name: client.agent_name,
      voice_id: client.voice_id,
    })
  }

  function handleEditCancel() {
    setEditingClient(null)
  }

  function handleEditSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!editingClient) return

    updateClientMutation.mutate(
      {
        clientId: editingClient.client_id,
        payload: {
          name: editForm.name || undefined,
          agent_name: editForm.agent_name || undefined,
          voice_id: editForm.voice_id || undefined,
        },
      },
      {
        onSuccess: () => {
          showToast('Client updated successfully', 'success')
          setEditingClient(null)
        },
        onError: (err) => {
          showToast(`Error updating client: ${err.message}`, 'error')
        },
      },
    )
  }

  // ── Deactivate Client ──────────────────────────────────────────────────────

  function handleDeactivate(e: React.MouseEvent, clientId: string) {
    e.stopPropagation() // prevent row click from navigating
    deactivateClientMutation.mutate(clientId, {
      onSuccess: () => {
        showToast('Client deactivated', 'success')
      },
      onError: (err) => {
        showToast(`Error deactivating client: ${err.message}`, 'error')
      },
    })
  }

  // ── Row click → navigate to detail ────────────────────────────────────────

  function handleRowClick(clientId: string) {
    void navigate(`/admin/clients/${clientId}`)
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

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink">Clients</h1>
          <p className="text-sm text-ink-3 mt-1">Manage your Qora clients</p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setShowCreateForm((v) => !v)}
        >
          {showCreateForm ? 'Cancel' : '+ New Client'}
        </Button>
      </div>

      {/* Create Client form — shown when toggled */}
      {showCreateForm && (
        <Card>
          <div className="flex items-center justify-between mb-4">
            <p className="text-[0.72rem] font-semibold uppercase tracking-[0.08em] text-ink-3">
              New Client
            </p>
          </div>
          <form onSubmit={handleCreateSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Input
                label="Client ID"
                placeholder="acme-motors"
                value={createForm.client_id}
                onChange={(e) => setCreateForm((f) => ({ ...f, client_id: e.target.value }))}
                required
              />
              <Input
                label="Name"
                placeholder="Acme Motors"
                value={createForm.name}
                onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
              <Input
                label="Agent Name"
                placeholder="Jaumpablo"
                value={createForm.agent_name}
                onChange={(e) => setCreateForm((f) => ({ ...f, agent_name: e.target.value }))}
              />
            </div>
            <div className="flex justify-end">
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={createClientMutation.isPending}
              >
                {createClientMutation.isPending ? 'Creating…' : 'Create Client'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {/* Edit Client inline panel */}
      {editingClient && (
        <Card className="border-teal-line bg-teal-faint/40">
          <div className="mb-4">
            <p className="text-[0.72rem] font-semibold uppercase tracking-[0.08em] text-ink-3">
              Edit Client
            </p>
            <code className="text-teal font-mono text-xs mt-0.5 block">{editingClient.client_id}</code>
          </div>
          <form onSubmit={handleEditSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Input
                label="Name"
                value={editForm.name}
                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
              />
              <Input
                label="Agent Name"
                value={editForm.agent_name}
                onChange={(e) => setEditForm((f) => ({ ...f, agent_name: e.target.value }))}
              />
              <Input
                label="Voice ID"
                value={editForm.voice_id}
                onChange={(e) => setEditForm((f) => ({ ...f, voice_id: e.target.value }))}
              />
            </div>
            <div className="flex gap-2 justify-end">
              <Button type="button" variant="tertiary" size="sm" onClick={handleEditCancel}>
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={updateClientMutation.isPending}
              >
                {updateClientMutation.isPending ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {/* Clients table */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.08em] text-ink-3">
            All Clients
          </p>
        </div>

        {isLoading && (
          <div data-testid="clients-loading" className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-10 bg-mist rounded-md animate-pulse" />
            ))}
          </div>
        )}

        {isError && (
          <div data-testid="clients-error" role="alert" className="py-8 text-center">
            <p className="text-ink font-medium">Unable to load clients. Please try again.</p>
          </div>
        )}

        {!isLoading && !isError && clients && clients.length === 0 && (
          <div data-testid="clients-empty" className="py-8 text-center">
            <p className="text-ink font-medium">No clients found</p>
            <p className="text-ink-3 text-sm mt-1">Create the first client above.</p>
          </div>
        )}

        {!isLoading && !isError && clients && clients.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Agents</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {clients.map((client) => (
                <TableRow
                  key={client.client_id}
                  data-testid={`client-row-${client.client_id}`}
                  onClick={() => handleRowClick(client.client_id)}
                  className="cursor-pointer"
                >
                  <TableCell>
                    <code className="font-mono text-xs text-teal">{client.client_id}</code>
                  </TableCell>
                  <TableCell className="font-medium text-ink">{client.name}</TableCell>
                  <TableCell>{client.agent_name}</TableCell>
                  <TableCell>
                    {client.agent_count !== undefined ? client.agent_count : '—'}
                  </TableCell>
                  <TableCell>
                    <Badge status={client.is_active ? 'active' : 'neutral'}>
                      {client.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={(e) => handleEditClick(e, client)}
                      >
                        Edit
                      </Button>
                      {client.is_active && (
                        <Button
                          variant="tertiary"
                          size="sm"
                          className="text-error hover:text-error"
                          onClick={(e) => handleDeactivate(e, client.client_id)}
                          disabled={deactivateClientMutation.isPending}
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
    </div>
  )
}
