/**
 * Lightweight local toast — matches design's .toast pill (dashboard.css).
 * Not a shared design-system component: scoped to the Import feature only.
 */

import { useCallback, useEffect, useState } from 'react'

export function useToast() {
  const [message, setMessage] = useState<string | null>(null)

  const showToast = useCallback((text: string) => {
    setMessage(text)
  }, [])

  useEffect(() => {
    if (!message) return
    const timer = setTimeout(() => setMessage(null), 3200)
    return () => clearTimeout(timer)
  }, [message])

  return { toastMessage: message, showToast }
}

export function Toast({ message }: { message: string }) {
  return (
    <div className="toast" role="status">
      <i className="dot" />
      <span>{message}</span>
    </div>
  )
}
