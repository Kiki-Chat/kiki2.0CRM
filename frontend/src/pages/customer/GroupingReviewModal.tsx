import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

import { Modal } from '../../components/ui/Modal'
import { Tag } from '../../components/ui/Tag'
import { apiFetch } from '../../lib/api'
import { cn } from '../../lib/utils'
import type { Proposal } from './types'

export function GroupingReviewModal({
  customerId,
  proposal,
  onClose,
  onApplied,
}: {
  customerId: string
  proposal: Proposal
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
          {proposal.n_inquiries} Anfragen analysiert ({proposal.model}). Haken = als einen Vorgang bündeln.
        </p>
        {merges.length === 0 && <p className="py-6 text-center text-sm text-muted">Kein Bündelungsvorschlag.</p>}
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
