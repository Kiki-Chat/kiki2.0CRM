// Drag-to-resize for the list / right panels (ported verbatim). Width persists
// per-key in localStorage so the user's chosen layout survives reloads.
import { useEffect, useState, type MouseEvent as ReactMouseEvent } from 'react'

export function useColumnResize(
  storageKey: string,
  initial: number,
  opts: { min: number; max: number; side: 'left' | 'right' },
) {
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem(storageKey))
    return saved >= opts.min && saved <= opts.max ? saved : initial
  })
  useEffect(() => {
    localStorage.setItem(storageKey, String(width))
  }, [storageKey, width])
  const onMouseDown = (e: ReactMouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = width
    const onMove = (ev: MouseEvent) => {
      const delta = opts.side === 'left' ? ev.clientX - startX : startX - ev.clientX
      setWidth(Math.min(opts.max, Math.max(opts.min, startW + delta)))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }
  return { width, onMouseDown }
}

export function ResizeHandle({ onMouseDown }: { onMouseDown: (e: ReactMouseEvent) => void }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onMouseDown={onMouseDown}
      className="w-1 flex-shrink-0 cursor-col-resize bg-border/40 transition-colors hover:bg-green-primary/50"
    />
  )
}
