import { useState, useEffect, useCallback } from 'react'

/**
 * Lightweight transient toast. Owns the auto-dismiss timer via an effect so it's
 * always cleaned up on unmount (no dangling setTimeout). `flash(message)` shows a
 * toast that clears itself after `ms`; `setToast` is exposed for manual control.
 */
export function useToast(ms = 4000) {
  const [toast, setToast] = useState<string | null>(null)
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), ms)
    return () => clearTimeout(id)
  }, [toast, ms])
  const flash = useCallback((m: string) => setToast(m), [])
  return { toast, flash, setToast }
}
