/**
 * ImportPage — Coming Soon
 * CSV bulk lead import — not yet implemented.
 */

import { useParams } from 'react-router'

export function ImportPage() {
  const { clientId } = useParams<{ clientId: string }>()

  return (
    <div>
      <h1 className="font-display text-2xl font-medium text-ink">
        Import
      </h1>
      {clientId && (
        <p className="text-sm text-ink-2 mt-1">
          Client: <span className="text-teal font-medium">{clientId}</span>
        </p>
      )}
      <p className="text-ink-3 mt-4">
        CSV bulk lead import is coming soon.
      </p>
    </div>
  )
}
