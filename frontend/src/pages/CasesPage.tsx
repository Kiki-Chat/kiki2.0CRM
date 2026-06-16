// Cases (Fälle) — the dirC "Karteikarte" split view. Left: a filterable, date-grouped
// case list. Right: one readable case card (header + focused "Was ist zu tun?" + quick
// actions + record tables incl. Techniker). Clicking an Anfrage opens that call's
// transcript/audio drawer in-place (the same LogDrawer as Anrufe). Deep-linkable via
// ?case=<id> (call-log chip / project-from-case round-trip / legacy /fall/:id).
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { apiFetch } from '../lib/api'
import { useToast } from '../lib/useToast'
import { CaseDetailPane } from './cases/CaseDetailPane'
import { CaseList } from './cases/CaseList'
import type { CaseListRow, Employee, ProjectRow } from './cases/types'
import { LogDrawer } from './calls/log/LogDrawer'
import type { RawAction } from './posteingang/api'

export function CasesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { toast, flash } = useToast()
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get('case'))
  const [drawerCallId, setDrawerCallId] = useState<string | null>(null)

  const { data: cases = [] } = useQuery({ queryKey: ['cases'], queryFn: () => apiFetch<CaseListRow[]>('/api/cases') })
  const { data: employees = [] } = useQuery({ queryKey: ['pe', 'employees'], queryFn: () => apiFetch<Employee[]>('/api/employees'), staleTime: 60_000 })
  const { data: projects = [] } = useQuery({ queryKey: ['projects'], queryFn: () => apiFetch<ProjectRow[]>('/api/projects'), staleTime: 60_000 })
  const { data: pendingActions = [] } = useQuery({ queryKey: ['pe', 'actions'], queryFn: () => apiFetch<RawAction[]>('/api/actions/pending'), refetchInterval: 30_000, staleTime: 15_000 })

  // Effective selection: explicit pick / ?case= deep-link, else the newest case.
  const effectiveId = selectedId ?? cases[0]?.id ?? null

  // Honour later ?case= changes (project-from-case round-trip, dashboard links).
  const appliedCase = useRef<string | null>(searchParams.get('case'))
  useEffect(() => {
    const c = searchParams.get('case')
    if (c && c !== appliedCase.current) {
      appliedCase.current = c
      setSelectedId(c)
    }
  }, [searchParams])

  const select = (id: string) => {
    setSelectedId(id)
    setSearchParams((p) => { p.set('case', id); return p }, { replace: true })
  }

  return (
    <div className="flex h-full overflow-hidden bg-surface">
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-lg bg-text px-4 py-2 text-sm font-semibold text-bg shadow-e3">{toast}</div>
      )}
      <CaseList cases={cases} selectedId={effectiveId} onSelect={select} />
      <CaseDetailPane
        key={effectiveId ?? 'none'}
        caseId={effectiveId}
        employees={employees}
        projects={projects}
        allCases={cases}
        pendingActions={pendingActions}
        onOpenCall={(id) => setDrawerCallId(id)}
        flash={flash}
      />
      <LogDrawer callId={drawerCallId} onClose={() => setDrawerCallId(null)} flash={flash} />
    </div>
  )
}
