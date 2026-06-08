/**
 * LiveIndicator — Animated "live/broadcasting" status indicator
 *
 * Qora Design System — reusable visual primitive.
 * Direct copy of CodePen pulse pattern with inline styles.
 * Color: teal (#1A8B7A). Self-contained — no external CSS needed.
 *
 * Sizes:
 *  - sm: 8px dot   (inline with text, agent cards)
 *  - md: 12px dot  (cards, lists)
 *  - lg: 18px dot  (hero, feature callout)
 */

interface LiveIndicatorProps {
  /** Visual size preset */
  size?: 'sm' | 'md' | 'lg'
  /** Additional CSS classes on the outer wrapper */
  className?: string
}

const sizePx = {
  sm: 8,
  md: 12,
  lg: 18,
}

const STYLE_ID = 'qora-live-indicator-styles'

const cssText = `
@keyframes qora-live-pulse {
  0% {
    transform: scale(0.33);
    opacity: 0.6;
  }
  80%, 100% {
    opacity: 0;
  }
}

@keyframes qora-live-circle {
  0% {
    transform: scale(0.8);
  }
  50% {
    transform: scale(1);
  }
  100% {
    transform: scale(0.8);
  }
}

.qora-live-indicator {
  position: relative;
  display: inline-block;
  flex-shrink: 0;
}

.qora-live-indicator::before {
  content: "";
  position: relative;
  display: block;
  width: 300%;
  height: 300%;
  box-sizing: border-box;
  margin-left: -100%;
  margin-top: -100%;
  border-radius: 50%;
  background-color: #1A8B7A;
  animation: qora-live-pulse 1.25s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
}

.qora-live-indicator::after {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  display: block;
  width: 100%;
  height: 100%;
  background-color: #1A8B7A;
  border-radius: 50%;
  box-shadow: 0 0 8px rgba(26, 139, 122, 0.6);
  animation: qora-live-circle 1.25s cubic-bezier(0.455, 0.03, 0.515, 0.955) -0.4s infinite;
}
`

function ensureStyles() {
  if (typeof document === 'undefined') return
  if (document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = cssText
  document.head.appendChild(style)
}

export function LiveIndicator({ size = 'md', className = '' }: LiveIndicatorProps) {
  ensureStyles()
  const dot = sizePx[size]

  return (
    <span
      className={`qora-live-indicator ${className}`}
      aria-label="Live"
      role="status"
      style={{ width: dot, height: dot }}
    />
  )
}
