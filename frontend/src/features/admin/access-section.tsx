/**
 * AccessSection — superadmin WorkOS organization linking for a client (multi-tenant-auth §8, §9)
 *
 * States:
 *  - No organization linked: "Conectar con WorkOS" button
 *  - Linked: organization id, members list, pending invitations (revocable),
 *    and an invite-by-email form
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  Button,
  Input,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  Toast,
} from '@/design/components'
import { useAccessState, useLinkOrganization, useCreateInvitation, useRevokeInvitation } from '@/api/hooks'
import { ApiError } from '@/api/client'

interface ToastState {
  message: string
  status: 'success' | 'error'
}

interface AccessSectionProps {
  clientId: string
}

function isAuthNotConfigured(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 503 || error.reason === 'auth_not_configured')
}

function inviteErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.reason === 'organization_not_linked') {
      return 'Vinculá la organización con WorkOS antes de invitar miembros.'
    }
    if (isAuthNotConfigured(error)) {
      return 'La integración con WorkOS no está configurada.'
    }
    return error.message
  }
  return 'No se pudo enviar la invitación.'
}

export function AccessSection({ clientId }: AccessSectionProps) {
  const access = useAccessState(clientId)
  const linkMutation = useLinkOrganization(clientId)
  const inviteMutation = useCreateInvitation(clientId)
  const revokeMutation = useRevokeInvitation(clientId)

  const [email, setEmail] = useState('')
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)

  if (access.isLoading) {
    return (
      <p data-testid="access-loading" className="text-sm text-ink-3">
        Cargando acceso…
      </p>
    )
  }

  if (access.isError || !access.data) {
    return (
      <p role="alert" className="text-sm text-coral">
        {isAuthNotConfigured(access.error)
          ? 'La integración con WorkOS no está configurada.'
          : 'No se pudo cargar el acceso de este cliente.'}
      </p>
    )
  }

  const { organization_id: organizationId, members, invitations } = access.data

  function handleLink() {
    linkMutation.mutate(undefined, {
      onError: () => setToast({ message: 'No se pudo vincular la organización.', status: 'error' }),
    })
  }

  function handleInvite(e: FormEvent) {
    e.preventDefault()
    setInviteError(null)
    inviteMutation.mutate(email.trim(), {
      onSuccess: () => {
        setEmail('')
        setToast({ message: 'Invitación enviada.', status: 'success' })
      },
      onError: (err) => setInviteError(inviteErrorMessage(err)),
    })
  }

  function handleRevoke(invitationId: string) {
    revokeMutation.mutate(invitationId, {
      onError: () => setToast({ message: 'No se pudo revocar la invitación.', status: 'error' }),
    })
  }

  return (
    <div className="space-y-5">
      {toast && <Toast message={toast.message} status={toast.status} onDismiss={() => setToast(null)} />}

      {organizationId ? (
        <p className="text-sm text-ink-3">
          Organización vinculada:{' '}
          <code className="font-mono text-xs text-teal" data-testid="access-organization-id">
            {organizationId}
          </code>
        </p>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-ink-3">Este cliente todavía no tiene una organización de WorkOS vinculada.</p>
          <Button onClick={handleLink} disabled={linkMutation.isPending} data-testid="link-organization-button">
            {linkMutation.isPending ? 'Vinculando…' : 'Conectar con WorkOS'}
          </Button>
        </div>
      )}

      <div>
        <p className="text-xs font-medium uppercase tracking-widest text-ink-3 mb-2">Miembros</p>
        {members.length === 0 ? (
          <p className="text-sm text-ink-3">No hay miembros todavía.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Nombre</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => (
                <TableRow key={member.user_id}>
                  <TableCell>{member.email}</TableCell>
                  <TableCell>{member.name ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <div>
        <p className="text-xs font-medium uppercase tracking-widest text-ink-3 mb-2">Invitaciones pendientes</p>
        {invitations.length === 0 ? (
          <p className="text-sm text-ink-3">No hay invitaciones pendientes.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Vence</TableHead>
                <TableHead aria-hidden="true" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.map((invitation) => (
                <TableRow key={invitation.id}>
                  <TableCell>{invitation.email}</TableCell>
                  <TableCell>{invitation.expires_at}</TableCell>
                  <TableCell>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleRevoke(invitation.id)}
                      disabled={revokeMutation.isPending}
                      data-testid={`revoke-invitation-${invitation.id}`}
                    >
                      Revocar
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <form onSubmit={handleInvite} className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-widest text-ink-3">Invitar por email</p>
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <Input
              id="invite-email"
              type="email"
              label="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <Button type="submit" disabled={inviteMutation.isPending}>
            {inviteMutation.isPending ? 'Invitando…' : 'Invitar'}
          </Button>
        </div>
        {inviteError && (
          <p role="alert" className="text-sm text-coral">
            {inviteError}
          </p>
        )}
      </form>
    </div>
  )
}
