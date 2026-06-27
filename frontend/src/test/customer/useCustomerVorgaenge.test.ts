import { describe, expect, it } from 'vitest'

import type { CaseCardRow, InquiryRow } from '../../pages/customer/types'
import {
  filterCasesBySearch,
  filterCasesByStatus,
  filterOrphansBySearch,
  filterPickerTargets,
  groupCasesByActivityDate,
  orphanInquiries,
  resolveInquiryForCallEvent,
  statusFilterCounts,
} from '../../pages/customer/useCustomerVorgaenge'

const NOW = Date.parse('2026-06-27T12:00:00Z')

const cases: CaseCardRow[] = [
  {
    id: 'c1', number: 'VG-1', label: 'Badsanierung', status: 'active', created_at: '2026-06-10T10:00:00Z',
    project_id: null, ai_summary: 'Sanierung läuft', call_count: 2, entry_count: 4,
    last_activity_at: '2026-06-27T09:00:00Z',
  },
  {
    id: 'c2', number: 'VG-2', label: 'Therme', status: 'completed', created_at: '2026-05-01T10:00:00Z',
    project_id: null, ai_summary: 'Erledigt', call_count: 1, entry_count: 2,
    last_activity_at: '2026-05-21T10:00:00Z',
  },
  {
    id: 'c3', number: 'VG-3', label: 'Neu', status: 'planning', created_at: '2026-06-26T10:00:00Z',
    project_id: null, ai_summary: 'Offen', call_count: 0, entry_count: 0,
    last_activity_at: '2026-06-26T16:00:00Z',
  },
]

const inquiries: InquiryRow[] = [
  { id: 'i1', number: 'ANF-1', title: 'Bad', subject: 'Bad', type: null, status: 'open', created_at: '2026-06-10T10:00:00Z', case_id: 'c1' },
  { id: 'i2', number: 'ANF-2', title: 'Hahn', subject: 'Hahn tropft', type: null, status: 'open', created_at: '2026-06-26T10:00:00Z', case_id: null,
    primary_call: { id: 'call-1', summary_title: 'Meldung Hahn', direction: 'inbound', duration_seconds: 88, started_at: '2026-06-26T16:40:00Z' } },
]

describe('filterCasesByStatus', () => {
  it('returns all cases when filter is all', () => {
    expect(filterCasesByStatus(cases, 'all')).toHaveLength(3)
  })
  it('filters by planning/active/completed chip keys', () => {
    expect(filterCasesByStatus(cases, 'open')).toHaveLength(1)
    expect(filterCasesByStatus(cases, 'in_progress')).toHaveLength(1)
    expect(filterCasesByStatus(cases, 'completed')).toHaveLength(1)
  })
})

describe('filterCasesBySearch', () => {
  it('matches label and ai_summary case-insensitively', () => {
    expect(filterCasesBySearch(cases, 'sanierung')).toHaveLength(1)
    expect(filterCasesBySearch(cases, 'therme')).toHaveLength(1)
  })
})

describe('groupCasesByActivityDate', () => {
  it('puts recent activity in Heute bucket', () => {
    const groups = groupCasesByActivityDate(cases, NOW)
    expect(groups[0]?.label).toBe('Heute')
    expect(groups[0]?.items.some((c) => c.id === 'c1')).toBe(true)
  })
})

describe('orphanInquiries', () => {
  it('returns only case_id=null inquiries', () => {
    expect(orphanInquiries(inquiries)).toHaveLength(1)
    expect(orphanInquiries(inquiries)[0].id).toBe('i2')
  })
})

describe('filterOrphansBySearch', () => {
  it('matches inquiry subject and primary call title', () => {
    expect(filterOrphansBySearch(orphanInquiries(inquiries), 'hahn')).toHaveLength(1)
    expect(filterOrphansBySearch(orphanInquiries(inquiries), 'meldung')).toHaveLength(1)
  })
})

describe('resolveInquiryForCallEvent', () => {
  it('maps call entity_id to inquiry_id', () => {
    const calls = [{ id: 'call-1', inquiry_id: 'i2' }]
    expect(resolveInquiryForCallEvent('call-1', calls)).toBe('i2')
    expect(resolveInquiryForCallEvent('missing', calls)).toBeNull()
  })
})

describe('filterPickerTargets', () => {
  it('excludes completed cases in assign mode', () => {
    const targets = filterPickerTargets(cases, 'assign')
    expect(targets.some((c) => c.status === 'completed')).toBe(false)
  })
  it('excludes source case in transfer mode', () => {
    const targets = filterPickerTargets(cases, 'transfer', 'c1')
    expect(targets.some((c) => c.id === 'c1')).toBe(false)
  })
})

describe('statusFilterCounts', () => {
  it('counts cases per status chip', () => {
    expect(statusFilterCounts(cases)).toEqual({ all: 3, open: 1, in_progress: 1, completed: 1 })
  })
})
