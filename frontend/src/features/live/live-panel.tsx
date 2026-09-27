/**
 * LivePanel — "En vivo" live calls canvas, driven by real data.
 *
 * Ported from /Users/mati/Downloads/qora-presentacion/project/dashboard/screens-live.jsx
 * (the `Live` component + app.css "live world" section — classes already
 * ported to frontend/src/design/dashboard.css with `--qd-*` vars).
 *
 * Unlike the presentation prototype, this component never simulates calls or
 * facts — every dot, line, and feed entry comes from useLiveCalls(clientId).
 * Only the ambient motion (breathing core, flowing lines, rotating rings) is
 * purely decorative.
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
/** Duration of a lead "flying in" toward its agent when a call first appears. */
const ENTRY_S = 1.8
const END_FADE_MS = 1400
const LABEL_SYNC_S = 0.4

interface AgentLayout {
  id: string
  name: string
  isLive: boolean
  x: number
  y: number
}

interface Point {
  x: number
  y: number
}

interface LabelPositions {
  mem: Point
  agents: Record<string, Point>
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

/** Pick a free angle for a new lead around its agent, facing away from the memory core. */
function pickAngle(agent: AgentLayout, taken: number[]): number {
  const base = Math.atan2((MEM.y - agent.y) * 9, (MEM.x - agent.x) * 16) + Math.PI
  const offsets = [0, -0.75, 0.75, -1.5, 1.5, -2.2, 2.2]
  for (const o of offsets) {
    const g = base + o
    if (!taken.some((a) => Math.abs(Math.atan2(Math.sin(a - g), Math.cos(a - g))) < 0.5)) return g
  }
  return base + taken.length * 0.4
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
  const { agents, calls, activeTotal, newFacts, recentFacts, memoryTotal, today } = useLiveCalls(clientId)
  const { data: client } = useClient(clientId)
  const [clock, setClock] = useState(() => new Date())
  const [labels, setLabels] = useState<LabelPositions | null>(null)

  const timeZone = resolveTimezone(client?.scheduler_timezone)
  const tzAbbrevFormatter = useRef(
    new Intl.DateTimeFormat('es-AR', { timeZone, timeZoneName: 'short' }),
  )
  useEffect(() => {
    tzAbbrevFormatter.current = new Intl.DateTimeFormat('es-AR', { timeZone, timeZoneName: 'short' })
  }, [timeZone])

  // Feed shows the most recent 6 facts; newly-arrived ones lead the list.
  // Derived (not state) so it always belongs to the current client's latest
  // poll: it empties while a new client loads and when the API returns none.
  const feed = recentFacts.slice(0, 6)

  const talkingCount = calls.filter((c) => c.state === 'talk').length

  const hasMemoryData = recentFacts.length > 0 || memoryTotal > 0

  // ── Canvas render loop ──────────────────────────────────────────────────
  const callsRef = useRef<CanvasCall[]>(calls)
  callsRef.current = calls
  const agentLayout = layoutAgents(agents)
  const agentsRef = useRef(agentLayout)
  agentsRef.current = agentLayout
  interface MemoryParticle {
    agentId: string | null
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
    newFacts.forEach((_, i) => {
      particlesRef.current.push({ agentId: source.id, t0: performance.now() / 1000 + i * 0.25 })
    })
  }, [newFacts])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return // jsdom / no-canvas-support guard

    let width = 0
    let height = 0
    let dpr = 1
    let raf = 0
    let grid: HTMLCanvasElement | null = null
    let lastLabelSync = 0
    let lastLabelKey = ''
    // Per-call visual state that the API doesn't carry: a stable angle around
    // the agent and the moment the call first appeared (for the fly-in).
    const callVisuals = new Map<string, { angle: number; born: number }>()

    const build = () => {
      const rect = wrap.getBoundingClientRect()
      width = rect.width
      height = rect.height
      if (!width || !height) return
      dpr = Math.min(2, window.devicePixelRatio || 1)
      canvas.width = width * dpr
      canvas.height = height * dpr

      // Pre-render the dot grid once per size; it's static and costly per frame.
      grid = document.createElement('canvas')
      grid.width = canvas.width
      grid.height = canvas.height
      const g = grid.getContext('2d')
      if (!g) return
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
      const M = memPos()
      const R = Math.max(width, height) * 0.62
      for (let x = 12; x < width; x += 22) {
        for (let y = 12; y < height; y += 22) {
          const d = Math.hypot(x - M.x, y - M.y)
          const a = 0.03 + 0.085 * Math.max(0, 1 - d / R)
          g.fillStyle = `rgba(${INK},${a})`
          g.fillRect(x - 0.75, y - 0.75, 1.5, 1.5)
        }
      }
    }

    const narrow = () => width < 760
    const callRadius = () => Math.max(80, Math.min(190, Math.min(width, height) * 0.2))
    const memPos = (): Point =>
      narrow() ? { x: width * 0.56, y: height * 0.5 } : { x: MEM.x * width, y: MEM.y * height }
    // Keep agent nodes (and their lead fan) inside the canvas bounds.
    const agentPos = (a: AgentLayout): Point => {
      const idle = !a.isLive
      const r = callRadius()
      const mx = idle ? 70 : r + 96
      const my = idle ? 70 : r + 60
      const ax = narrow() && idle ? 0.88 : a.x
      const ay = narrow() ? (idle ? 0.22 : 0.46) : a.y
      return {
        x: Math.min(width - mx, Math.max(mx, ax * width)),
        y: Math.min(height - r - 110, Math.max(my, ay * height)),
      }
    }

    build()
    const ro = new ResizeObserver(build)
    ro.observe(wrap)

    const draw = (nowMs: number) => {
      if (!width || !height || !grid) return
      const t = nowMs / 1000
      const wall = Date.now()

      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(grid, 0, 0)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      // Memory core — breathing halo, rotating dashed ring, pulse on new facts.
      const M = memPos()
      ;[70, 130, 205, 300].forEach((r, i) => {
        ctx.beginPath()
        ctx.arc(M.x, M.y, r + Math.sin(t * 0.6 + i) * 2, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(${INK},.04)`
        ctx.lineWidth = 1
        ctx.stroke()
      })
      const pulse = pulseRef.current
      const br = 1 + Math.sin(t * 1.1) * 0.04 + pulse * 0.12
      ctx.beginPath()
      ctx.arc(M.x, M.y, 46 * br, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${TEAL},${0.06 + pulse * 0.08})`
      ctx.fill()
      ctx.save()
      ctx.translate(M.x, M.y)
      ctx.rotate(t * 0.1)
      ctx.setLineDash([2, 7])
      ctx.beginPath()
      ctx.arc(0, 0, 58 * br, 0, Math.PI * 2)
      ctx.strokeStyle = `rgba(${TEAL},.5)`
      ctx.lineWidth = 1.2
      ctx.stroke()
      ctx.restore()
      ctx.setLineDash([])
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
      pulseRef.current = Math.max(0, pulseRef.current - 0.01)

      // Drop visuals for calls that are gone for good.
      const liveIds = new Set(callsRef.current.map((c) => c.sessionId))
      for (const id of callVisuals.keys()) if (!liveIds.has(id)) callVisuals.delete(id)

      // Agent nodes + their calls.
      for (const a of agentsRef.current) {
        const A = agentPos(a)

        ctx.beginPath()
        ctx.moveTo(A.x, A.y)
        ctx.lineTo(M.x, M.y)
        ctx.setLineDash(a.isLive ? [1, 6] : [3, 8])
        ctx.lineDashOffset = a.isLive ? -t * 14 : 0
        ctx.strokeStyle = a.isLive ? `rgba(${TEAL},.3)` : `rgba(${INK},.1)`
        ctx.lineWidth = 1.2
        ctx.stroke()
        ctx.setLineDash([])
        ctx.lineDashOffset = 0

        const agentCalls = callsRef.current.filter((c) => c.agentId === a.id)
        const r = callRadius()
        for (const c of agentCalls) {
          let vis = callVisuals.get(c.sessionId)
          if (!vis) {
            const taken = agentCalls
              .map((o) => callVisuals.get(o.sessionId)?.angle)
              .filter((x): x is number => x != null)
            vis = { angle: pickAngle(a, taken), born: t }
            callVisuals.set(c.sessionId, vis)
          }
          const ang = vis.angle
          const T = { x: A.x + Math.cos(ang) * r, y: A.y + Math.sin(ang) * r }
          const entry = Math.min(1, (t - vis.born) / ENTRY_S)

          // Fly-in: the lead travels from off-canvas toward its slot.
          if (entry < 1 && c.state !== 'end') {
            const far = Math.max(width, height) * 0.9
            const F = { x: A.x + Math.cos(ang) * far, y: A.y + Math.sin(ang) * far }
            const e = easeIO(entry)
            const L = { x: F.x + (T.x - F.x) * e, y: F.y + (T.y - F.y) * e }
            for (let i = 0; i < 6; i++) {
              const back = i * 7
              ctx.beginPath()
              ctx.arc(L.x + Math.cos(ang) * back, L.y + Math.sin(ang) * back, 3 - i * 0.4, 0, Math.PI * 2)
              ctx.fillStyle = `rgba(${INK},${0.5 - i * 0.08})`
              ctx.fill()
            }
            continue
          }

          const L = T
          const alpha = c.state === 'end' ? Math.max(0, 1 - (wall - c.since) / END_FADE_MS) : 1
          if (alpha <= 0) continue
          const dx = L.x - A.x
          const dy = L.y - A.y
          const dl = Math.hypot(dx, dy) || 1
          const sx = A.x + (dx / dl) * 30
          const sy = A.y + (dy / dl) * 30

          ctx.beginPath()
          ctx.moveTo(sx, sy)
          ctx.lineTo(L.x, L.y)
          if (c.state === 'dial') {
            ctx.setLineDash([3, 5])
            ctx.strokeStyle = `rgba(${INK},${0.18 + 0.14 * Math.sin(t * 8)})`
          } else {
            ctx.strokeStyle = `rgba(${TEAL},${0.4 * alpha})`
          }
          ctx.lineWidth = 1.2
          ctx.stroke()
          ctx.setLineDash([])

          if (c.state === 'talk') {
            // Voice particles; direction flips every few seconds (who's speaking).
            const seed = (vis.born * 7) % 3
            const speaker = Math.floor((t - vis.born) / 3.2 + seed) % 2
            for (let k = 0; k < 3; k++) {
              let s = (t * 0.7 + k / 3 + seed) % 1
              if (speaker) s = 1 - s
              const x = sx + (L.x - sx) * s
              const y = sy + (L.y - sy) * s
              ctx.beginPath()
              ctx.arc(x, y, 1.8, 0, Math.PI * 2)
              ctx.fillStyle = `rgba(${speaker ? INK : TEAL},${Math.sin(s * Math.PI) * 0.95})`
              ctx.fill()
            }
            const ph = ((t - vis.born) * 0.8) % 1
            ctx.beginPath()
            ctx.arc(L.x, L.y, 5 + ph * 14, 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(${TEAL},${(1 - ph) * 0.4})`
            ctx.lineWidth = 1
            ctx.stroke()
          }

          ctx.beginPath()
          ctx.arc(L.x, L.y, 4.5, 0, Math.PI * 2)
          ctx.fillStyle = c.state === 'talk' ? `rgba(${TEAL},${alpha})` : `rgba(${INK},${0.55 * alpha})`
          ctx.fill()

          if (c.leadFirstName) {
            const right = Math.cos(ang) >= 0
            ctx.font = '500 11px "JetBrains Mono", monospace'
            ctx.textBaseline = 'middle'
            ctx.textAlign = right ? 'left' : 'right'
            ctx.fillStyle = `rgba(${INK},${(c.state === 'talk' ? 0.7 : 0.4) * alpha})`
            const text = c.state === 'dial' ? `${c.leadFirstName} · marcando` : c.leadFirstName
            ctx.fillText(text, L.x + (right ? 14 : -14), L.y)
          }
        }

        const active = agentCalls.filter((c) => c.state === 'talk' || c.state === 'dial')
        const talking = active.some((c) => c.state === 'talk')

        // Radiating rings while the agent is in a conversation.
        if (a.isLive && talking) {
          for (let k = 0; k < 3; k++) {
            const ph = (t * 0.4 + k / 3) % 1
            ctx.beginPath()
            ctx.arc(A.x, A.y, 30 + ph * 60, 0, Math.PI * 2)
            ctx.strokeStyle = `rgba(${TEAL},${(1 - ph) * 0.25})`
            ctx.lineWidth = 1
            ctx.stroke()
          }
        }

        ctx.beginPath()
        ctx.arc(A.x, A.y, 28, 0, Math.PI * 2)
        ctx.fillStyle = '#0A0B0E'
        ctx.fill()
        if (a.isLive) {
          ctx.strokeStyle = `rgba(${TEAL},.85)`
          ctx.lineWidth = 1.5
          ctx.stroke()
        } else {
          ctx.save()
          ctx.translate(A.x, A.y)
          ctx.rotate(-t * 0.2)
          ctx.setLineDash([4, 6])
          ctx.beginPath()
          ctx.arc(0, 0, 28, 0, Math.PI * 2)
          ctx.strokeStyle = `rgba(${INK},.3)`
          ctx.lineWidth = 1.2
          ctx.stroke()
          ctx.restore()
          ctx.setLineDash([])
        }

        // Inner ring: one arc segment per active line.
        const n = Math.max(1, active.length)
        ctx.lineCap = 'round'
        for (let i = 0; i < n; i++) {
          const s0 = -Math.PI / 2 + i * ((Math.PI * 2) / n) + 0.12
          const s1 = -Math.PI / 2 + (i + 1) * ((Math.PI * 2) / n) - 0.12
          const c = active[i]
          ctx.beginPath()
          ctx.arc(A.x, A.y, 15, s0, s1)
          ctx.strokeStyle = c
            ? c.state === 'talk'
              ? `rgba(${TEAL},.95)`
              : `rgba(${INK},${0.25 + 0.2 * Math.sin(t * 8)})`
            : `rgba(${INK},${a.isLive ? 0.12 : 0.08})`
          ctx.lineWidth = 2.5
          ctx.stroke()
        }
        ctx.lineCap = 'butt'
        if (!a.isLive) {
          ctx.beginPath()
          ctx.arc(A.x, A.y, 3, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${INK},.3)`
          ctx.fill()
        }
      }

      // Memory particles — trail from the agent node to the core, then pulse.
      particlesRef.current = particlesRef.current.filter((p) => {
        const k = (t - p.t0) / 1.3
        if (k < 0) return true
        const source = agentsRef.current.find((a) => a.id === p.agentId)
        if (!source) return false
        const from = agentPos(source)
        const e = easeIO(Math.min(1, k))
        for (let i = 0; i < 8; i++) {
          const ee = Math.max(0, e - i * 0.03)
          ctx.beginPath()
          ctx.arc(from.x + (M.x - from.x) * ee, from.y + (M.y - from.y) * ee, 3 - i * 0.3, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(${TEAL},${1 - i * 0.12})`
          ctx.fill()
        }
        if (k >= 1) {
          pulseRef.current = 1
          return false
        }
        return true
      })

      // Keep the HTML labels glued to the clamped canvas positions.
      if (t - lastLabelSync > LABEL_SYNC_S) {
        lastLabelSync = t
        const next: LabelPositions = { mem: M, agents: {} }
        for (const a of agentsRef.current) next.agents[a.id] = agentPos(a)
        const key = JSON.stringify(next)
        if (key !== lastLabelKey) {
          lastLabelKey = key
          setLabels(next)
        }
      }
    }

    const frame = (now: number) => {
      if (!document.hidden) draw(now)
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

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
  const memStyle = labels
    ? { left: labels.mem.x, top: labels.mem.y }
    : { left: `${MEM.x * 100}%`, top: `${MEM.y * 100}%` }
  const feedStyle = labels
    ? { left: labels.mem.x + 96, top: labels.mem.y }
    : { left: `calc(${MEM.x * 100}% + 96px)`, top: `${MEM.y * 100}%` }

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
          {activeTotal} en curso · {totalToday} llamadas hoy
        </p>
      </div>
      <div className="w-top-r">
        <span className="mono num" style={{ fontSize: 12, letterSpacing: '.08em', color: 'var(--qd-ink-3)' }}>
          {tzAbbrevFormatter.current.format(clock)}
        </span>
      </div>

      {hasMemoryData && (
        <>
          <div className="w-mem" style={memStyle}>
            <span className="num" style={{ font: '500 15px/1 var(--qd-F)', letterSpacing: '-.01em', color: 'var(--qd-ink)', textTransform: 'none' }}>
              {memoryTotal.toLocaleString('es-AR')}
            </span>
            <span>Memoria</span>
          </div>
          <div className="w-feed" style={feedStyle}>
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

      {agentLayout.map((a) => {
        const talk = calls.filter((c) => c.agentId === a.id && c.state === 'talk').length
        const dialing = calls.filter((c) => c.agentId === a.id && c.state === 'dial').length
        const pos = labels?.agents[a.id]
        return (
          <div
            key={a.id}
            className="w-label"
            style={pos ? { left: pos.x, top: pos.y } : { left: `${a.x * 100}%`, top: `${a.y * 100}%` }}
          >
            <b>{a.name}</b>
            <span className={a.isLive && talk > 0 ? 'on' : undefined}>
              {!a.isLive ? 'Configurando' : `${talk + dialing} en curso`}
            </span>
          </div>
        )
      })}

      <div className="w-dock">
        {agentLayout.map((a) => {
          const todayCount = calls.filter((c) => c.agentId === a.id && c.state !== 'end').length
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
