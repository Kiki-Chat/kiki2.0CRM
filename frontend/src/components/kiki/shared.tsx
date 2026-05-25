import type { ReactNode } from 'react'

import { cn } from '../../lib/utils'
import { Modal } from '../ui/Modal'
import { Tag } from '../ui/Tag'

export const inputCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2 text-sm text-text outline-none focus:border-green-primary'
export const labelCls = 'mb-1 block text-xs font-semibold text-body'

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('rounded-xl border border-border bg-surface p-6', className)}>{children}</div>
}

export function GroupLabel({ children }: { children: ReactNode }) {
  return <div className="mb-3 text-xs font-bold uppercase tracking-wide text-muted">{children}</div>
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <div className={labelCls}>{label}</div>
      {children}
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

export function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn(
        'relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50',
        on ? 'bg-green-primary' : 'bg-border',
      )}
    >
      <span className={cn('absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all', on ? 'left-[22px]' : 'left-0.5')} />
    </button>
  )
}

export function SaveBar({
  onReset,
  onSave,
  saving,
  resetLabel = 'Zurücksetzen',
  saveLabel = 'Speichern',
  disabled,
}: {
  onReset: () => void
  onSave: () => void
  saving: boolean
  resetLabel?: string
  saveLabel?: string
  disabled?: boolean
}) {
  return (
    <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
      <button onClick={onReset} className="text-sm font-medium text-muted hover:text-body">{resetLabel}</button>
      <button
        onClick={onSave}
        disabled={saving || disabled}
        className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
      >
        {saving ? 'Speichert…' : saveLabel}
      </button>
    </div>
  )
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  message,
  confirmLabel = 'Fortfahren',
  onConfirm,
  busy,
  danger,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: string
  message: ReactNode
  confirmLabel?: string
  onConfirm: () => void
  busy?: boolean
  danger?: boolean
}) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <div className="flex gap-3">
          <button onClick={() => onOpenChange(false)} className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body">
            Abbrechen
          </button>
          <button
            disabled={busy}
            onClick={onConfirm}
            className={cn('flex-1 rounded-md py-2.5 text-sm font-semibold text-white disabled:opacity-50', danger ? 'bg-error' : 'bg-green-primary')}
          >
            {busy ? 'Wird angewendet…' : confirmLabel}
          </button>
        </div>
      }
    >
      <div className="text-sm text-body">{message}</div>
    </Modal>
  )
}

const RESOURCE_STATUS: Record<string, { label: string; variant: 'neutral' | 'info' | 'success' | 'error' }> = {
  pending: { label: 'Wartet', variant: 'neutral' },
  processing: { label: 'Verarbeitung', variant: 'info' },
  ready: { label: 'Bereit', variant: 'success' },
  error: { label: 'Fehler', variant: 'error' },
}

export function StatusBadge({ status }: { status: string }) {
  const s = RESOURCE_STATUS[status] || RESOURCE_STATUS.pending
  return <Tag variant={s.variant}>{s.label}</Tag>
}

export function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-lg font-bold text-text">{title}</h2>
      {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
    </div>
  )
}
