/**
 * useClientId — reads :clientId from route params
 * Throws if called outside a route that has :clientId.
 */

import { useParams } from 'react-router'

export function useClientId(): string {
  const { clientId } = useParams<{ clientId: string }>()
  if (!clientId) {
    throw new Error('useClientId must be used inside a route with :clientId param')
  }
  return clientId
}
