// Shared case-grouping controls — used by BOTH the Customer detail and the Case
// detail so "move an inquiry to another Fall" + "KI-Gruppierung" behave identically
// wherever cases are managed. Endpoints: POST /api/inquiries/{id}/case (move),
// POST /api/customers/{id}/cases/propose + POST /api/cases/apply (AI grouping).
import { useMutation } from '@tanstack/react-query'
import { MoreVertical } from 'lucide-react'
import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { apiFetch } from '../../lib/api'
import { cn } from '../../lib/utils'
import { Modal } from '../ui/Modal'
import { Tag } from '../ui/Tag'

export interface MoveTarget {
  id: string
  label: string | null
  number?: string | null
}

/** A per-inquiry "⋮" menu: ungroup, move into another of the customer's cases, or
 *  spin up a new case. Render inside a `relative` row. The popover is portalled to
 *  <body> (fixed-positioned under the trigger) so it is never clipped by a scroll/
 *  overflow ancestor — e.g. the case detail's `overflow-x-auto` record tables. */
export function MoveMenu({
  inquiryId,
  currentCaseId,
  cases,
  onMoved,
}: {
  inquiryId: string
  currentCaseId?: string | null
  cases: MoveTarget[]
  onMoved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const move = useMutation({
    mutationFn: (body: { case_id?: string | null; new_case_label?: string }) =>
      apiFetch(`/api/inquiries/${inquiryId}/case`, { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => {
      setOpen(false)
      onMoved()
    },
  })
  const others = cases.filter((c) => c.id !== currentCaseId)
  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) })
    }
    setOpen((o) => !o)
  }
  const itemCls = 'block w-full truncate rounded px-2.5 py-1.5 text-left text-sm text-body hover:bg-alt'
  return (
    <div className="absolute right-2 top-2">
      <button
        ref={btnRef}
        onClick={(e) => {
          e.stopPropagation()
          toggle()
        }}
        className="rounded p-1 text-faint hover:bg-border"
        title="In anderen Vorgang verschieben"
      >
        <MoreVertical size={15} />
      </button>
      {open &&
        pos &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[60]" onClick={() => setOpen(false)} />
            <div
              className="fixed z-[61] max-h-[60vh] w-60 overflow-y-auto rounded-lg border border-border bg-surface p-1 shadow-e3"
              style={{ top: pos.top, right: pos.right }}
              onClick={(e) => e.stopPropagation()}
            >
              {currentCaseId && (
                <button onClick={() => move.mutate({ case_id: null })} className={itemCls}>
                  Aus Vorgang lösen
                </button>
              )}
              <div className="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-faint">In Vorgang verschieben</div>
              {others.length > 0 ? (
                others.map((c) => (
                  <button key={c.id} onClick={() => move.mutate({ case_id: c.id })} className={itemCls}>
                    → {c.label || 'Vorgang'}
                    {c.number ? <span className="ml-1 font-mono text-xs text-muted">{c.number}</span> : null}
                  </button>
                ))
              ) : (
                <div className="px-2.5 py-1.5 text-xs text-muted">Keine weiteren Vorgänge dieses Kunden.</div>
              )}
              <button
                onClick={() => {
                  const l = window.prompt('Neuer Vorgang — Thema:')
                  if (l) move.mutate({ new_case_label: l })
                }}
                className="block w-full rounded px-2.5 py-1.5 text-left text-sm font-medium text-green-deep hover:bg-alt"
              >
                ＋ Neuer Vorgang…
              </button>
            </div>
          </>,
          document.body,
        )}
    </div>
  )
}

export interface GroupProposal {
  model: string
  n_inquiries: number
  cost: number
  cases: { label: string; members: string[]; confidence: number; reason: string; tier: string }[]
}

/** Review the KI grouping proposal (pick which bundles to materialise) → apply. */
export function GroupingReviewModal({
  customerId,
  proposal,
  onClose,
  onApplied,
}: {
  customerId: string
  proposal: GroupProposal
  onClose: () => void
  onApplied: () => void
}) {
  const merges = proposal.cases.filter((c) => c.members.length >= 2)
  const [picked, setPicked] = useState<Set<number>>(
    () => new Set(merges.map((_, idx) => idx).filter((idx) => merges[idx].tier !== 'low')),
  )
  const toggle = (idx: number) =>
    setPicked((s) => {
      const n = new Set(s)
      if (n.has(idx)) n.delete(idx)
      else n.add(idx)
      return n
    })
  const apply = useMutation({
    mutationFn: () =>
      apiFetch('/api/cases/apply', {
        method: 'POST',
        body: JSON.stringify({ customer_id: customerId, groups: merges.filter((_, idx) => picked.has(idx)) }),
      }),
    onSuccess: onApplied,
  })
  const tierTag = (t: string) =>
    t === 'auto' ? <Tag variant="success">sicher</Tag> : t === 'review' ? <Tag variant="warning">Prüfen</Tag> : <Tag variant="neutral">unsicher</Tag>
  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title="KI-Vorschlag: Anfragen zu Fällen bündeln"
      widthClass="max-w-2xl"
      footer={
        <button
          onClick={() => apply.mutate()}
          disabled={apply.isPending || picked.size === 0}
          className="w-full rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {picked.size} Vorgänge übernehmen
        </button>
      }
    >
      <div className="space-y-2">
        <p className="text-xs text-muted">
          {proposal.n_inquiries} Anfragen analysiert ({proposal.model}). Haken = als einen Vorgang bündeln; einzelne Anfragen
          kannst du danach jederzeit verschieben.
        </p>
        {merges.length === 0 && <p className="py-6 text-center text-sm text-muted">Kein Bündelungsvorschlag — alle Anfragen wirken eigenständig.</p>}
        {merges.map((c, idx) => (
          <label
            key={idx}
            className={cn('flex cursor-pointer gap-3 rounded-lg border p-3', picked.has(idx) ? 'border-green-primary bg-green-tint-100' : 'border-border')}
          >
            <input type="checkbox" checked={picked.has(idx)} onChange={() => toggle(idx)} className="mt-1 flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="flex-1 truncate text-sm font-bold text-text">{c.label}</span>
                {tierTag(c.tier)}
                <span className="text-xs font-bold text-ai">{Math.round(c.confidence * 100)}%</span>
              </div>
              <div className="mt-1 font-mono text-xs text-muted">{c.members.join(', ')}</div>
              <div className="mt-1 text-xs text-body">{c.reason}</div>
            </div>
          </label>
        ))}
      </div>
    </Modal>
  )
}
