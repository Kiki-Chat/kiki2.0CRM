// Renders the Anrufe LogTable to lock in the two call-log changes:
//   1. The Betreff column shows the German `issue_summary` (the ElevenLabs
//      Betreffzeile-prompt output) in preference to EL's generic, often-English
//      `summary_title`.
//   2. The caller name is a link to the customer page when the call is tied to a
//      customer, and plain text otherwise.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CallListItem } from '../shared'
import { LogTable, type DayGroup } from './LogTable'

function makeCall(over: Partial<CallListItem> = {}): CallListItem {
  return {
    id: 'call-1',
    elevenlabs_conversation_id: null,
    caller_number: '+49 170 1234567',
    summary_title: 'Heater Repair Request', // EL's generic built-in title (English)
    direction: 'inbound',
    duration_seconds: 140,
    started_at: '2026-06-27T08:00:00Z',
    data_collection: { issue_summary: 'Gasheizung defekt – Räume kalt' },
    customer_id: 'cust-1',
    read_at: '2026-06-27T09:00:00Z',
    created_at: '2026-06-27T08:00:00Z',
    customers: { full_name: 'Max Mustermann' },
    inquiry_id: null,
    inquiry_status: null,
    inquiry_number: null,
    inquiry_subject: null,
    case_id: null,
    case_number: null,
    case_label: null,
    project_id: null,
    project_number: null,
    project_title: null,
    emergency_flag: false,
    assigned_employee_id: null,
    assigned_employee_initials: null,
    ...over,
  }
}

function renderTable(calls: CallListItem[]) {
  const onOpenCase = vi.fn()
  const dayGroups: DayGroup[] = [{ key: 'd1', label: 'Heute', calls }]
  render(
    <LogTable
      dayGroups={dayGroups}
      selectedId={null}
      employeeName={new Map()}
      onSelect={vi.fn()}
      onOpenCase={onOpenCase}
    />,
  )
  return { onOpenCase }
}

describe('LogTable — Betreff from issue_summary', () => {
  it('shows the German issue_summary, not the generic English summary_title', () => {
    renderTable([makeCall()])
    expect(screen.getByText('Gasheizung defekt – Räume kalt')).toBeInTheDocument()
    expect(screen.queryByText('Heater Repair Request')).not.toBeInTheDocument()
  })

  it('falls back to summary_title when there is no issue_summary', () => {
    renderTable([makeCall({ id: 'c2', data_collection: null, summary_title: 'Rückfrage Anfahrtszeit' })])
    expect(screen.getByText('Rückfrage Anfahrtszeit')).toBeInTheDocument()
  })

  it('shows "Ohne Betreff" when neither issue_summary nor summary_title exists', () => {
    renderTable([makeCall({ id: 'c3', data_collection: null, summary_title: null })])
    expect(screen.getByText('Ohne Betreff')).toBeInTheDocument()
  })
})

describe('LogTable — clickable customer name', () => {
  it('links the name to the customer page and navigates on click', () => {
    const { onOpenCase } = renderTable([makeCall({ customer_id: 'cust-42' })])
    const nameBtn = screen.getByRole('button', { name: 'Max Mustermann' })
    fireEvent.click(nameBtn)
    expect(onOpenCase).toHaveBeenCalledWith('/customers/cust-42')
  })

  it('renders the name as plain text (no link) for an unlinked caller', () => {
    renderTable([
      makeCall({
        id: 'c-anon',
        customer_id: null,
        customers: null,
        data_collection: { customer_name: 'Anon Caller' },
      }),
    ])
    expect(screen.getByText('Anon Caller')).toBeInTheDocument()
    // exact-name match: the row <tr> button's name is the long aria-label, so only a
    // dedicated name button would match here — and there must be none.
    expect(screen.queryByRole('button', { name: 'Anon Caller' })).not.toBeInTheDocument()
  })
})
