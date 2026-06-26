// Left pane of the Cases split-view: "Meine Fälle" + search + two big dropdown
// filters (Status / Kontakt) + a scrollable list of case rows grouped under date
// dividers (Heute / Gestern / "Montag, 16. Juni") by last activity. Each row shows
// the customer, the case title, and the case STATUS chip (Offen / In Arbeit / Fertig).
import { Check, ChevronDown, Layers, Search, User, X } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'

import { cn, initials } from '../../lib/utils'
import { dayDividerLabel, dayKeyOf } from '../calls/log/util'
import type { CaseListRow } from './types'

const ts = (iso: string | null) => (iso ? new Date(iso).getTime() : 0)
const NOW = Date.now()

const LIST_STATUS: Record<string, { label: string; cls: string }> = {
  planning: { label: 'Offen', cls: 'bg-info-bg text-info' },
  active: { label: 'In Arbeit', cls: 'bg-warning-bg text-warning' },
  completed: { label: 'Abgeschlossen', cls: 'bg-success-bg text-success' },
  archived: { label: 'Archiviert', cls: 'bg-alt text-muted' },
}

function CaseAvatar({ name, size = 50 }: { name: string | null; size?: number }) {
  return (
    <span className="flex flex-shrink-0 items-center justify-center rounded-full bg-alt font-extrabold text-body ring-1 ring-inset ring-border" style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }}>
      {initials(name ?? '?')}
    </span>
  )
}

interface Opt { value: string; label: string; dot?: string; count?: number }

function Dropdown({ icon: Icon, value, options, onChange, allLabel }: {
  icon: typeof Layers
  value: string
  options: Opt[]
  onChange: (v: string) => void
  allLabel: string
}) {
  const [open, setOpen] = useState(false)
  const cur = options.find((o) => o.value === value)
  const active = value !== 'all'
  const all: Opt[] = [{ value: 'all', label: allLabel }, ...options]
  return (
    <div className="relative min-w-0 flex-1">
      <button onClick={() => setOpen((o) => !o)} className={cn('flex w-full items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-sm font-bold transition', active ? 'border-green-primary bg-green-tint-50 text-green-deep' : 'border-border bg-surface text-body hover:bg-alt')}>
        <Icon size={16} className={active ? 'text-green-deep' : 'text-muted'} />
        <span className="min-w-0 flex-1 truncate">{cur ? cur.label : allLabel}</span>
        <ChevronDown size={15} className={cn('text-muted transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="scroll absolute left-0 right-0 top-[calc(100%+6px)] z-50 max-h-80 overflow-y-auto rounded-xl border border-border bg-surface p-1.5 shadow-e3">
            {all.map((o) => {
              const on = o.value === value
              return (
                <button key={o.value} onClick={() => { onChange(o.value); setOpen(false) }} className={cn('flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition', on ? 'bg-green-tint-50 font-extrabold text-green-deep' : 'font-semibold text-body hover:bg-alt')}>
                  {o.dot && <span className="h-2 w-2 flex-shrink-0 rounded-full" style={{ background: o.dot }} />}
                  <span className="min-w-0 flex-1 truncate">{o.label}</span>
                  {o.count != null && <span className={cn('text-xs font-bold', on ? 'text-green-deep' : 'text-faint')}>{o.count}</span>}
                  {on && <Check size={15} className="text-green-deep" />}
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

function CaseRow({ c, active, onSelect }: { c: CaseListRow; active: boolean; onSelect: () => void }) {
  const st = LIST_STATUS[c.status] ?? LIST_STATUS.planning
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect() } }}
      className={cn('flex cursor-pointer items-center gap-3.5 rounded-2xl p-4 outline-none transition', active ? 'bg-green-tint-50 ring-[1.5px] ring-inset ring-green-primary' : 'bg-surface ring-1 ring-inset ring-border hover:bg-alt', 'focus-visible:ring-[1.5px] focus-visible:ring-green-primary')}
    >
      <CaseAvatar name={c.customer_name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[17px] font-extrabold text-text">{c.customer_name || 'Unbekannt'}</div>
        <div className="mt-0.5 truncate text-[14.5px] text-muted">{c.title || 'Vorgang'}</div>
      </div>
      <div className="flex flex-shrink-0 items-center gap-2">
        {c.emergency && <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-error" title="Notdienst" />}
        <span className={cn('rounded-xl px-3 py-1.5 text-[13px] font-extrabold', st.cls)}>{st.label}</span>
      </div>
    </div>
  )
}

export function CaseList({ cases, selectedId, onSelect }: {
  cases: CaseListRow[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const [search, setSearch] = useState('')
  const [statusF, setStatusF] = useState('all')
  const [contactF, setContactF] = useState('all')
  const q = search.trim().toLowerCase()

  const filtered = useMemo(
    () =>
      cases
        .filter((c) =>
          (!q || (c.customer_name ?? '').toLowerCase().includes(q) || (c.title ?? '').toLowerCase().includes(q)) &&
          (statusF === 'all' || (statusF === 'emergency' ? c.emergency : c.status === statusF)) &&
          (contactF === 'all' || c.customer_name === contactF))
        .sort((a, b) => ts(b.updated_at || b.created_at) - ts(a.updated_at || a.created_at)),
    [cases, q, statusF, contactF],
  )

  // Date dividers (Heute / Gestern / full date) by last activity — newest first.
  const groups = useMemo(() => {
    const out: { key: string; label: string; items: CaseListRow[] }[] = []
    for (const c of filtered) {
      const iso = c.updated_at || c.created_at
      const key = dayKeyOf(iso)
      const last = out[out.length - 1]
      if (last && last.key === key) last.items.push(c)
      else out.push({ key, label: dayDividerLabel(iso, NOW), items: [c] })
    }
    return out
  }, [filtered])

  const statusOpts: Opt[] = [
    { value: 'emergency', label: 'Notdienst', dot: 'var(--error)', count: cases.filter((c) => c.emergency).length },
    { value: 'planning', label: 'Offen', dot: 'var(--info)', count: cases.filter((c) => c.status === 'planning').length },
    { value: 'active', label: 'In Arbeit', dot: 'var(--warning)', count: cases.filter((c) => c.status === 'active').length },
    { value: 'completed', label: 'Abgeschlossen', dot: 'var(--success)', count: cases.filter((c) => c.status === 'completed').length },
  ]
  const contactOpts: Opt[] = [...new Set(cases.map((c) => c.customer_name).filter(Boolean) as string[])]
    .sort((a, b) => a.localeCompare(b, 'de'))
    .map((n) => ({ value: n, label: n, count: cases.filter((c) => c.customer_name === n).length }))
  const activeFilters = (statusF !== 'all' ? 1 : 0) + (contactF !== 'all' ? 1 : 0)

  return (
    <div className="flex w-full flex-shrink-0 flex-col border-r border-border bg-bg md:w-[420px]">
      <div className="px-5 pb-4 pt-6">
        <div className="flex items-baseline gap-2.5">
          <h1 className="font-poster text-[26px] font-extrabold text-text">Meine Vorgänge</h1>
          <span className="text-[15px] font-bold text-muted">{filtered.length} von {cases.length}</span>
        </div>
        <div className="relative mt-3.5">
          <Search size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name suchen…" className="w-full rounded-xl border border-border bg-surface py-3 pl-11 pr-3.5 text-[15.5px] text-text outline-none focus:border-green-primary" />
        </div>
        <div className="mt-3 flex gap-2.5">
          <Dropdown icon={Layers} value={statusF} onChange={setStatusF} allLabel="alle" options={statusOpts} />
          <Dropdown icon={User} value={contactF} onChange={setContactF} allLabel="alle" options={contactOpts} />
        </div>
        {activeFilters > 0 && (
          <button onClick={() => { setStatusF('all'); setContactF('all') }} className="mt-2.5 inline-flex items-center gap-1.5 text-[13.5px] font-bold text-green-deep hover:underline">
            <X size={14} /> Filter zurücksetzen
          </button>
        )}
      </div>

      <div className="scroll flex flex-1 flex-col gap-2.5 overflow-y-auto px-4 pb-5">
        {filtered.length ? (
          groups.map((g) => (
            <Fragment key={g.key}>
              <div className="flex items-center gap-2 px-1 pt-1">
                <span className="text-[12px] font-extrabold capitalize tracking-wide text-muted">{g.label}</span>
                <span className="h-px flex-1 bg-border-faint" />
                <span className="text-[11px] font-bold text-faint">{g.items.length}</span>
              </div>
              {g.items.map((c) => <CaseRow key={c.id} c={c} active={c.id === selectedId} onSelect={() => onSelect(c.id)} />)}
            </Fragment>
          ))
        ) : (
          <div className="px-5 py-10 text-center">
            <Search size={28} className="mx-auto text-faint" />
            <div className="mt-2.5 text-[15px] font-bold text-body">Keine Vorgänge gefunden</div>
            <div className="mt-1 text-[13.5px] text-muted">Versuche einen anderen Filter.</div>
          </div>
        )}
      </div>
    </div>
  )
}
