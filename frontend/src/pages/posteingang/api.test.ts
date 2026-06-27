// buildDecisions: the vorgang_merge_suggested action becomes a real decision card
// with Zusammenführen / Ablehnen and carries the target Vorgang for the merge POST.
import { describe, expect, it } from 'vitest'

import { buildDecisions, type RawAction } from './api'

describe('buildDecisions — vorgang_merge_suggested', () => {
  it('maps a merge suggestion to a Zusammenführen / Ablehnen decision card', () => {
    const a: RawAction = {
      action_key: 'vorgang_merge_suggested:c-src',
      kind: 'vorgang_merge_suggested',
      id: 'c-src',
      inquiry_id: null,
      call_id: null,
      customer_id: 'cust-1',
      customer_name: 'Max Mustermann',
      summary: '„Heizung Bad“ gehört vermutlich zum offenen Vorgang „Heizung defekt“ — zusammenführen?',
      priority: 'normal',
      target_case_id: 'c-tgt',
    }
    const [d] = buildDecisions([a], [], new Map())
    expect(d.kind).toBe('vorgang_merge_suggested')
    expect(d.notify).toBe(false) // a real in-card decision, not a notify-only card
    expect(d.primary).toBe('Zusammenführen')
    expect(d.tertiary).toBe('Ablehnen')
    expect(d.targetCaseId).toBe('c-tgt')
    expect(d.customer).toBe('Max Mustermann')
    expect(d.snippet).toContain('zusammenführen')
  })
})
