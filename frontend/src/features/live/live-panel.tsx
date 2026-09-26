/**
 * LivePanel — "En vivo" live calls canvas, driven by real data.
 *
 * Ported from /Users/mati/Downloads/qora-presentacion/project/dashboard/screens-live.jsx
 * (the `Live` component + app.css "live world" section — classes already
 * ported to frontend/src/design/dashboard.css with `--qd-*` vars).
 *
 * Unlike the presentation prototype, this component never simulates calls or
 * facts — every dot, line, and feed entry comes from useLiveCalls(clientId).
 */

import { useEffect, useRef, useState } from 'react'
import { useClient } from '@/api/hooks'
import { resolveTimezone } from '@/lib/timezone'
import { useLiveCalls } from './use-live-calls'
import type { CanvasCall } from './call-state'
import type { LiveRecentFact } from '@/api/live'

const TEAL = '46,201,176'
const INK = '232,236,235'
const MEM = { x: 0.56, y: 0.52 }

interface AgentLayout {
  id: string
  name: string
  isLive: boolean
  x: number
  y: number
}

function layoutAgents(agents: { id: string; name: string; isLive: boolean }[]): AgentLayout[] {
  // Evenly distribute agents left-to-right around the memory core, mirroring
  // the prototype's fixed two-agent layout for the common 1-3 agent case.
  const xs = [0.24, 0.78, 0.5, 0.15, 0.85]
  const ys = [0.46, 0.3, 0.72, 0.6, 0.2]
  return agents.map((a, i) => ({
    ...a,
    x: xs[i % xs.length],
    y: ys[i % ys.length],
  }))
}

function easeIO(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
}

function feedKey(fact: LiveRecentFact, index: number): string {
  return `${fact.text}|${fact.lead_first_name ?? ''}|${index}`
}

function formatDuration(seconds: number | null): string | null {
  if (seconds == null) return null
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export interface LivePanelProps {
  clientId: string
  embedded?: boolean
}

export function LivePanel({ clientId, embedded }: LivePanelProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const { agents, calls, newFacts, recentFacts, memoryTotal, today } = useLiveCalls(clientId)
  const { data: client } = useClient(clientId)
  const [clock, setClock] = useState(() => new Date())
  const [feed, setFeed] = useState<LiveRecentFact[]>([])

  const timeZone = resolveTimezone(client?.scheduler_timezone)
  const tzAbbrevFormatter = useRef(
    new Intl.DateTimeFormat('es-AR', { timeZone, timeZoneName: 'short' }),
  )
  useEffect(() => {
    tzAbbrevFormatter.current = new Intl.DateTimeFormat('es-AR', { timeZone, timeZoneName: 'short' })
  }, [timeZone])

  // Feed shows the most recent 6 facts; newly-arrived ones lead the list.
  useEffect(() => {
    if (recentFacts.length > 0) setFeed(recentFacts.slice(0, 6))
  }, [recentFacts])

  const talkingCount = calls.filter((c) => c.state === 'talk').length

  const hasMemoryData = recentFacts.length > 0 || memoryTotal > 0

  // ── Canvas render loop ──────────────────────────────────────────────────
  const callsRef = useRef<CanvasCall[]>(calls)
  callsRef.current = calls
  const agentsRef = useRef(layoutAgents(agents))
  agentsRef.current = layoutAgents(agents)
  interface MemoryParticle {
    from: { x: number; y: number }
    t0: number
  }
  const particlesRef = useRef<MemoryParticle[]>([])
  const pulseRef = useRef(0)

  // A real new fact arrived — spawn a particle flying from a live agent to
  // the memory core (never simulated: only fires when newFacts is non-empty).
  useEffect(() => {
    if (newFacts.length === 0) return
    const liveAgents = agentsRef.current.filter((a) => a.isLive)
    const source = liveAgents[0] ?? agentsRef.current[0]
    if (!source) return
    newFacts.forEach(() => {
      particlesRef.current.push({ from: { x: source.x, y: source.y }, t0: performance.now() })
    })
  }, [newFacts])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return // jsdom / no-canvas-support guard

    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

    let width = 0
    let height = 0
    let dpr = 1
    let raf = 0

    const build = () => {
      const rect = wrap.getBoundingClientRect()
      width = rect.width
      height = rect.height
      if (!width || !height) return
      dpr = Math.min(2, window.devicePixelRatio || 1)
      canvas.width = width * dpr
      canvas.height = height * dpr
    }
    build()
    const ro = new ResizeObserver(build)
    ro.observe(wrap)

    const agentPos = (a: AgentLayout) => ({ x: a.x * width, y: a.y * height })
    const memPos = () => ({ x: MEM.x * width, y: MEM.y * height })

    const draw = (now: number) => {
      if (!width || !height) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, width, height)

      // Dot grid, faded near the memory core.
      const M = memPos()
      const R = Math.max(width, height) * 0.62
      for (let x = 12; x < width; x += 22) {
        for (let y = 12; y < height; y += 22) {
          const d = Math.hypot(x - M.x, y - M.y)
          const a = 0.03 + 0.085 * Math.max(0, 1 - d / R)
          ctx.fillStyle = `rgba(${INK},${a})`
          ctx.fillRect(x - 0.75, y - 0.75, 1.5, 1.5)
        }
      }

      // Memory core.
      const t = now / 1000
      ;[70, 130, 205, 300].forEach((r, i) => {
        ctx.beginPath()
        ctx.arc(M.x, M.y, r + (reducedMotion ? 0 : Math.sin(t * 0.6 + i) * 2), 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(${INK},.04)`
        ctx.lineWidth = 1
        ctx.stroke()
      })
      const pulse = Math.max(0, pulseRef.current)
      ctx.beginPath()
      ctx.arc(M.x, M.y, 46 + pulse * 6, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${TEAL},${0.06 + pulse * 0.08})`
      ctx.fill()
      ctx.beginPath()
      ctx.arc(M.x, M.y, 7, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${TEAL},1)`
      ctx.fill()
      if (pulse > 0) {
        const ph = 1 - pulse
        ctx.beginPath()
        ctx.arc(M.x, M.y, 58 + ph * 110, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(${TEAL},${pulse * 0.45})`
        ctx.lineWidth = 1.2
        ctx.stroke()
      }
      pulseRef.current = Math.max(0, pulseRef.current - 0.02)

      // Memory particles — fly from an agent node to the memory core, then pulse.
      const PARTICLE_DURATION_MS = 900
      particlesRef.current = particlesRef.current.filter((p) => {
        const elapsed = performance.now() - p.t0
        const k = Math.min(1, elapsed / PARTICLE_DURATION_MS)
        const e = easeIO(k)
        const from = { x: p.from.x * width, y: p.from.y * height }
        const x = from.x + (M.x - from.x) * e
        const y = from.y + (M.y - from.y) * e
        ctx.beginPath()
        ctx.arc(x, y, 3, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${TEAL},${1 - k * 0.3})`
        ctx.fill()
        if (k >= 1) {
          pulseRef.current = 1
          return false
        }
        return true
      })

      // Agent nodes + their calls.
      for (const a of agentsRef.current) {
        const A = agentPos(a)
        ctx.beginPath()
        ctx.moveTo(A.x, A.y)
        ctx.lineTo(M.x, M.y)
        ctx.setLineDash(a.isLive ? [1, 6] : [3, 8])
        ctx.strokeStyle = a.isLive ? `rgba(${TEAL},.3)` : `rgba(${INK},.1)`
        ctx.lineWidth = 1.2
        ctx.stroke()
        ctx.setLineDash([])

        const agentCalls = callsRef.current.filter((c) => c.agentId === a.id)
        agentCalls.forEach((c, i) => {
          const angle = -Math.PI / 2 + i * 0.9
          const r = Math.max(60, Math.min(140, Math.min(width, height) * 0.16))
          const L = { x: A.x + Math.cos(angle) * r, y: A.y + Math.sin(angle) * r }
          const alpha = c.state === 'end' ? Math.max(0, 1 - (now - c.since) / 1500) : 1

          ctx.beginPath()
          ctx.moveTo(A.x, A.y)
          ctx.lineTo(L.x, L.y)
          if (c.state === 'dial') {
            ctx.setLineDash([3, 5])
            ctx.strokeStyle = `rgba(${INK},.2)`
          } else {
            ctx.strokeStyle = `rgba(${TEAL},${0.4 * alpha})`
          }
          ctx.lineWidth = 1.2
          ctx.stroke()
          ctx.setLineDash([])

          if (c.state === 'talk' && !reducedMotion) {
            for (let k = 0; k < 3; k++) {
              const s = (t * 0.7 + k / 3) % 1
              const e = easeIO(s)
              const x = A.x + (L.x - A.x) * e
              const y = A.y + (L.y - A.y) * e
              ctx.beginPath()
              ctx.arc(x, y, 1.8, 0, Math.PI * 2)
              ctx.fillStyle = `rgba(${TEAL},${Math.sin(s * Math.PI) * 0.95})`
              ctx.fill()
            }
          }

          ctx.beginPath()
          ctx.arc(L.x, L.y, 4.5, 0, Math.PI * 2)
          ctx.fillStyle = c.state === 'talk' ? `rgba(${TEAL},${alpha})` : `rgba(${INK},${0.55 * alpha})`
          ctx.fill()

          if (c.leadFirstName) {
            ctx.font = '500 11px "JetBrains Mono", monospace'
            ctx.textBaseline = 'middle'
            ctx.textAlign = Math.cos(angle) >= 0 ? 'left' : 'right'
            ctx.fillStyle = `rgba(${INK},${(c.state === 'talk' ? 0.7 : 0.4) * alpha})`
            ctx.fillText(c.leadFirstName, L.x + (Math.cos(angle) >= 0 ? 10 : -10), L.y)
          }
        })

        ctx.beginPath()
        ctx.arc(A.x, A.y, 28, 0, Math.PI * 2)
        ctx.fillStyle = '#0A0B0E'
        ctx.fill()
        if (a.isLive) {
          ctx.strokeStyle = `rgba(${TEAL},.85)`
          ctx.lineWidth = 1.5
          ctx.stroke()
        } else {
          ctx.setLineDash([4, 6])
          ctx.strokeStyle = `rgba(${INK},.3)`
          ctx.lineWidth = 1.2
          ctx.stroke()
          ctx.setLineDash([])
        }
      }
    }

    const frame = (now: number) => {
      if (!document.hidden) draw(now)
      raf = requestAnimationFrame(frame)
    }

    if (reducedMotion) {
      draw(performance.now())
    } else {
      raf = requestAnimationFrame(frame)
    }

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [])

  // Clock tick (1s) — independent of the canvas rAF loop.
  useEffect(() => {
    const iv = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(iv)
  }, [])

  const totalToday = today?.calls_total ?? 0

  return (
    <div className={'world' + (embedded ? ' embedded' : '')} data-theme="dark" ref={wrapRef}>
      <canvas ref={canvasRef} />

      <div className="w-head">
        <span className="eyebrow" style={{ color: 'var(--qd-teal)' }}>
          <i className="pulse" style={{ marginRight: 2 }} />
          En vivo{client?.name ? ` · ${client.name}` : ''}
        </span>
        <h1>
          <em>{talkingCount}</em> {talkingCount === 1 ? 'llamada' : 'llamadas'} en curso
        </h1>
        <p className="mono num">
          {calls.length} en curso · {totalToday} llamadas hoy
        </p>
      </div>
      <div className="w-top-r">
        <span className="mono num" style={{ fontSize: 12, letterSpacing: '.08em', color: 'var(--qd-ink-3)' }}>
          {tzAbbrevFormatter.current.format(clock)}
        </span>
      </div>

      {hasMemoryData && (
        <>
          <div className="w-mem" style={{ left: `${MEM.x * 100}%`, top: `${MEM.y * 100}%` }}>
            <span className="num" style={{ font: '500 15px/1 var(--qd-F)', letterSpacing: '-.01em', color: 'var(--qd-ink)', textTransform: 'none' }}>
              {memoryTotal.toLocaleString('es-AR')}
            </span>
            <span>Memoria</span>
          </div>
          <div className="w-feed" style={{ left: `calc(${MEM.x * 100}% + 96px)`, top: `${MEM.y * 100}%` }}>
            {feed.map((f, i) => {
              const dur = formatDuration(f.duration_seconds)
              return (
                <div key={feedKey(f, i)} className="w-fact" style={{ opacity: 1 - i * 0.16 }}>
                  <span>
                    {f.lead_first_name}
                    {dur && <em> · {dur}</em>}
                  </span>
                  {f.text}
                </div>
              )
            })}
          </div>
        </>
      )}

      {agentsRef.current.map((a) => {
        const talk = calls.filter((c) => c.agentId === a.id && c.state === 'talk').length
        const dialing = calls.filter((c) => c.agentId === a.id && c.state === 'dial').length
        return (
          <div key={a.id} className="w-label" style={{ left: `${a.x * 100}%`, top: `${a.y * 100}%` }}>
            <b>{a.name}</b>
            <span>{!a.isLive ? 'Configurando' : `${talk + dialing} en curso`}</span>
          </div>
        )
      })}

      <div className="w-dock">
        {agentsRef.current.map((a) => {
          const todayCount = calls.filter((c) => c.agentId === a.id).length
          return (
            <div key={a.id} className="w-card">
              <span className={'dot ' + (a.isLive ? 'live' : 'setup')} />
              <div className="t">
                <b>{a.name}</b>
                <span>{a.isLive ? `${todayCount} llamadas ahora` : 'Todavía no llama'}</span>
              </div>
            </div>
          )
        })}
        <div className="w-legend">
          <span>
            <i style={{ background: 'var(--qd-teal)' }} />
            Conversación
          </span>
          <span>
            <i style={{ background: 'var(--qd-ink-3)' }} />
            Marcando
          </span>
          {hasMemoryData && (
            <span>
              <i style={{ background: 'var(--qd-teal)', borderRadius: 1, width: 10, height: 2 }} />
              Recuerdo guardado
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
