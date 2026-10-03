/**
 * AgentRevisionsPanel — active revision + rollback history for one agent
 *
 * Shared by agents-section.tsx (route-scoped, live) and agents-panel.tsx
 * (legacy, client-selector variant) edit panels.
 */

import { useState } from 'react'
import { Badge, Button } from '@/design/components'
import { useAgentRevisions, useRollbackAgentRevision } from '@/api/hooks'
import type { AgentConfigRevision } from '@/api/types'

function SyncStatusBadge({ status }: { status: string | null }) {
  switch (status) {
    case 'synced':
      return <Badge status="success">Synced</Badge>
    case 'drift':
      return <Badge status="warning">Drift</Badge>
    case 'error':
      return <Badge status="error">Sync error</Badge>
    case 'skipped':
      return <Badge status="neutral">Skipped</Badge>
    default:
      return <Badge status="neutral">Unknown</Badge>
  }
}

interface AgentRevisionsPanelProps {
  clientId: string
  agentId: string
}

export function AgentRevisionsPanel({ clientId, agentId }: AgentRevisionsPanelProps) {
  const { data: revisions, isLoading, isError } = useAgentRevisions(clientId, agentId)
  const rollbackMutation = useRollbackAgentRevision(clientId, agentId)
  const [confirmingRevisionId, setConfirmingRevisionId] = useState<string | null>(null)

  function handleRollback(revisionId: string) {
    rollbackMutation.mutate(revisionId, {
      onSuccess: () => setConfirmingRevisionId(null),
    })
  }

  if (isLoading) {
    return (
      <p className="text-xs text-ink-3" data-testid="revisions-loading">
        Loading revisions…
      </p>
    )
  }

  if (isError || !revisions) {
    return (
      <p className="text-xs text-coral" role="alert">
        Unable to load revisions.
      </p>
    )
  }

  if (revisions.length === 0) {
    return <p className="text-xs text-ink-3">No revisions yet.</p>
  }

  // list_revisions returns newest first, and every write path (create/rollback)
  // activates immediately — the first row is always the active revision.
  const [active, ...history] = revisions

  return (
    <div className="mb-6 p-4 rounded-md border border-line bg-mist/50" data-testid="agent-revisions-panel">
      <p className="text-xs font-medium uppercase tracking-widest text-ink-3 mb-3">
        Config Revisions
      </p>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm text-ink">Active: revision {active.revision_number}</span>
        <SyncStatusBadge status={active.elevenlabs_sync_status} />
      </div>
      {history.length > 0 && (
        <ul className="space-y-2" data-testid="revisions-history">
          {history.map((revision: AgentConfigRevision) => (
            <li
              key={revision.id}
              className="flex items-center justify-between gap-3 text-xs border border-line rounded-md px-3 py-2"
            >
              <div className="flex flex-col gap-0.5">
                <span className="text-ink">
                  Revision {revision.revision_number} · {revision.source} · {revision.created_by}
                </span>
                <span className="text-ink-3">
                  {new Date(revision.created_at).toLocaleString()}
                  {revision.note ? ` — ${revision.note}` : ''}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <SyncStatusBadge status={revision.elevenlabs_sync_status} />
                {confirmingRevisionId === revision.id ? (
                  <>
                    <Button
                      type="button"
                      variant="tertiary"
                      size="sm"
                      onClick={() => setConfirmingRevisionId(null)}
                      disabled={rollbackMutation.isPending}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      onClick={() => handleRollback(revision.id)}
                      disabled={rollbackMutation.isPending}
                    >
                      {rollbackMutation.isPending ? 'Rolling back…' : 'Confirm rollback'}
                    </Button>
                  </>
                ) : (
                  <Button
                    type="button"
                    variant="tertiary"
                    size="sm"
                    onClick={() => setConfirmingRevisionId(revision.id)}
                  >
                    Roll back
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
