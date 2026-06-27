import { dayDividerLabel } from '../calls/log/util'
import type { CaseCardRow, CustomerDetail, InquiryRow, StatusFilter } from './types'

/** UI filter chip → backend case.status */
export const STATUS_FILTER_TO_CASE: Record<Exclude<StatusFilter, 'all'>, string> = {
  open: 'planning',
  in_progress: 'active',
  completed: 'completed',
}

export const CASE_STATUS_RAIL: Record<string, string> = {
  planning: 'var(--info)',
  active: 'var(--warning)',
  completed: 'var(--success)',
  archived: 'var(--faint)',
}

const VG_ORDER = ['Heute', 'Gestern', 'Diese Woche', 'Diesen Monat', 'Früher']

function vgBucket(iso: string | null, nowMs: number): string {
  if (!iso) return 'Früher'
  const label = dayDividerLabel(iso, nowMs)
  if (label === 'Heute') return 'Heute'
  if (label === 'Gestern') return 'Gestern'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return 'Früher'
  const days = Math.floor((nowMs - t) / 86_400_000)
  if (days <= 7) return 'Diese Woche'
  if (days <= 31) return 'Diesen Monat'
  return 'Früher'
}

export function filterCasesByStatus(cases: CaseCardRow[], filter: StatusFilter): CaseCardRow[] {
  if (filter === 'all') return cases
  const status = STATUS_FILTER_TO_CASE[filter]
  return cases.filter((c) => c.status === status)
}

export function filterCasesBySearch(cases: CaseCardRow[], q: string): CaseCardRow[] {
  const needle = q.trim().toLowerCase()
  if (!needle) return cases
  return cases.filter((c) => {
    const hay = `${c.label ?? ''} ${c.ai_summary ?? ''} ${c.number ?? ''}`.toLowerCase()
    return hay.includes(needle)
  })
}

export function groupCasesByActivityDate(cases: CaseCardRow[], nowMs = Date.now()): { label: string; items: CaseCardRow[] }[] {
  const sorted = cases.slice().sort((a, b) => {
    const ta = Date.parse(a.last_activity_at ?? a.created_at ?? '') || 0
    const tb = Date.parse(b.last_activity_at ?? b.created_at ?? '') || 0
    return tb - ta
  })
  const map: Record<string, CaseCardRow[]> = {}
  for (const c of sorted) {
    const g = vgBucket(c.last_activity_at ?? c.created_at, nowMs)
    ;(map[g] = map[g] || []).push(c)
  }
  return VG_ORDER.filter((l) => map[l]?.length).map((l) => ({ label: l, items: map[l]! }))
}

export function orphanInquiries(inquiries: InquiryRow[]): InquiryRow[] {
  return inquiries.filter((i) => !i.case_id)
}

export function filterOrphansBySearch(inquiries: InquiryRow[], q: string): InquiryRow[] {
  const needle = q.trim().toLowerCase()
  if (!needle) return inquiries
  return inquiries.filter((i) => {
    const pc = i.primary_call
    const hay = `${i.subject ?? ''} ${i.title ?? ''} ${pc?.summary_title ?? ''}`.toLowerCase()
    return hay.includes(needle)
  })
}

export function groupOrphansByDate(inquiries: InquiryRow[], nowMs = Date.now()): { label: string; items: InquiryRow[] }[] {
  const sorted = inquiries.slice().sort((a, b) => {
    const ta = Date.parse(a.primary_call?.started_at ?? a.last_activity_at ?? a.created_at) || 0
    const tb = Date.parse(b.primary_call?.started_at ?? b.last_activity_at ?? b.created_at) || 0
    return tb - ta
  })
  const map: Record<string, InquiryRow[]> = {}
  for (const i of sorted) {
    const iso = i.primary_call?.started_at ?? i.last_activity_at ?? i.created_at
    const g = dayDividerLabel(iso, nowMs)
    ;(map[g] = map[g] || []).push(i)
  }
  return Object.entries(map).map(([label, items]) => ({ label, items }))
}

export function resolveInquiryForCallEvent(
  callId: string,
  calls: { id: string; inquiry_id: string | null }[],
): string | null {
  return calls.find((c) => c.id === callId)?.inquiry_id ?? null
}

export function filterPickerTargets(
  cases: CaseCardRow[],
  mode: 'assign' | 'transfer',
  fromCaseId?: string,
): CaseCardRow[] {
  let list = cases.filter((c) => c.status !== 'completed' && c.status !== 'archived')
  if (mode === 'transfer' && fromCaseId) list = list.filter((c) => c.id !== fromCaseId)
  return list.slice().sort((a, b) => {
    const ta = Date.parse(a.last_activity_at ?? a.created_at ?? '') || 0
    const tb = Date.parse(b.last_activity_at ?? b.created_at ?? '') || 0
    return ta - tb
  })
}

export function statusFilterCounts(cases: CaseCardRow[]) {
  return {
    all: cases.length,
    open: cases.filter((c) => c.status === 'planning').length,
    in_progress: cases.filter((c) => c.status === 'active').length,
    completed: cases.filter((c) => c.status === 'completed').length,
  }
}

export function addrStr(a: CustomerDetail['address']) {
  if (!a) return '—'
  if (typeof a === 'string') return a
  if (a.raw) return a.raw
  const line = [a.street, [a.postal_code, a.city].filter(Boolean).join(' ')]
    .filter(Boolean)
    .join(', ')
  return line || '—'
}
