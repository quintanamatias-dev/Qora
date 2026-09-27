/**
 * useLiveCalls — TanStack Query hook driving the "en vivo" canvas.
 *
 * Polls GET /api/v1/calls/active every 4s (paused while the tab is hidden),
 * and combines it with useAgents(clientId) to know which agents are "live"
 * (is_active && is_conversation_ready). Reconciles the raw API rows into
 * canvas-ready call states (see call-state.ts) across renders.
 */

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAgents } from '@/api/hooks'
import { fetchActiveCalls } from '@/api/live'
import type { LiveRecentFact, LiveToday } from '@/api/live'
import { detectNewFacts, reconcileCanvasCalls } from './call-state'
import type { CanvasCall } from './call-state'

const POLL_INTERVAL_MS = 4_000

export interface LiveAgent {
  id: string
  name: string
  isLive: boolean
}

export interface UseLiveCallsResult {
  isLoading: boolean
  agents: LiveAgent[]
  calls: CanvasCall[]
  /** True in-flight count; `calls` is capped server-side. */
  activeTotal: number
  /** Facts that were not present on the previous poll — drives the memory-particle animation. */
  newFacts: LiveRecentFact[]
  recentFacts: LiveRecentFact[]
  memoryTotal: number
  today: LiveToday | null
  serverTime: string | null
}

export function useLiveCalls(clientId: string): UseLiveCallsResult {
  const agentsQuery = useAgents(clientId)
  const activeQuery = useQuery({
    queryKey: ['live-calls', clientId],
    queryFn: () => fetchActiveCalls(clientId),
    enabled: Boolean(clientId),
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: false,
  })

  const [calls, setCalls] = useState<CanvasCall[]>([])
  const [newFacts, setNewFacts] = useState<LiveRecentFact[]>([])
  const seenFactSignatures = useRef<Set<string>>(new Set())
  const seenFirstPoll = useRef(false)

  // Switching client must not leak the previous client's calls/facts while
  // the new client's first poll is still in flight. Reset during render (not
  // in an effect) so no frame ever renders the previous client's state.
  const [stateClientId, setStateClientId] = useState(clientId)
  if (stateClientId !== clientId) {
    setStateClientId(clientId)
    setCalls([])
    setNewFacts([])
    seenFactSignatures.current = new Set()
    seenFirstPoll.current = false
  }

  useEffect(() => {
    if (!activeQuery.data) return
    const now = Date.now()
    setCalls((prev) => reconcileCanvasCalls(prev, activeQuery.data.calls, now))

    // Don't flag the very first poll's facts as "new" — that would replay the
    // entire backlog as fresh memory particles on mount.
    if (!seenFirstPoll.current) {
      seenFirstPoll.current = true
      const { seen } = detectNewFacts(seenFactSignatures.current, activeQuery.data.recent_facts)
      seenFactSignatures.current = seen
      return
    }

    const { newFacts: fresh, seen } = detectNewFacts(
      seenFactSignatures.current,
      activeQuery.data.recent_facts,
    )
    seenFactSignatures.current = seen
    if (fresh.length > 0) setNewFacts(fresh)
  }, [activeQuery.data])

  const agents: LiveAgent[] = (agentsQuery.data ?? []).map((a) => ({
    id: a.agent_id,
    name: a.name,
    isLive: a.is_active && a.is_conversation_ready,
  }))

  return {
    isLoading: activeQuery.isLoading || agentsQuery.isLoading,
    agents,
    calls,
    newFacts,
    activeTotal: activeQuery.data?.active_total ?? 0,
    recentFacts: activeQuery.data?.recent_facts ?? [],
    memoryTotal: activeQuery.data?.memory_total ?? 0,
    today: activeQuery.data?.today ?? null,
    serverTime: activeQuery.data?.server_time ?? null,
  }
}
