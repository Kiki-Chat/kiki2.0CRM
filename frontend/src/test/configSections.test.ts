import { describe, expect, it } from 'vitest'

import {
  EMERGENCY_KEYWORD_TEMPLATES,
  deriveFieldKey,
  employeeToOption,
  mergeKeywords,
  resolveEmployeeName,
} from '../components/kiki/ConfigSections'

// ─── 1. Emergency keyword-batch dedup (Notdienst → Gewerk-Vorlagen) ──────────
describe('mergeKeywords', () => {
  it('unions a batch into the existing list without duplicates', () => {
    const result = mergeKeywords(['Rohrbruch', 'Wasserschaden'], ['Wasserschaden', 'Gasgeruch'])
    expect(result).toEqual(['Rohrbruch', 'Wasserschaden', 'Gasgeruch'])
  })

  it('preserves order: existing first, then new-in-batch in batch order', () => {
    const result = mergeKeywords(['b', 'a'], ['c', 'a', 'd'])
    expect(result).toEqual(['b', 'a', 'c', 'd'])
  })

  it('appending the same batch twice is idempotent', () => {
    const batch = EMERGENCY_KEYWORD_TEMPLATES[0].keywords
    const once = mergeKeywords([], batch)
    const twice = mergeKeywords(once, batch)
    expect(twice).toEqual(once)
    // and equals the batch itself when starting from empty (no internal dupes)
    expect(once).toEqual(batch)
  })

  it('does not mutate the input arrays', () => {
    const existing = ['Rohrbruch']
    const batch = ['Gasgeruch']
    mergeKeywords(existing, batch)
    expect(existing).toEqual(['Rohrbruch'])
    expect(batch).toEqual(['Gasgeruch'])
  })

  it('appending an empty batch returns the existing list unchanged', () => {
    expect(mergeKeywords(['Rohrbruch'], [])).toEqual(['Rohrbruch'])
  })

  it('every shipped template is internally duplicate-free', () => {
    for (const t of EMERGENCY_KEYWORD_TEMPLATES) {
      expect(new Set(t.keywords).size).toBe(t.keywords.length)
    }
  })
})

// ─── 2. Employee → dropdown option mapping (Terminkategorien) ────────────────
describe('employeeToOption', () => {
  it('maps id → value and display_name → label', () => {
    expect(employeeToOption({ id: 'emp-1', display_name: 'Anna Müller' })).toEqual({
      value: 'emp-1',
      label: 'Anna Müller',
    })
  })

  it('falls back to a placeholder label when display_name is null', () => {
    expect(employeeToOption({ id: 'emp-2', display_name: null })).toEqual({
      value: 'emp-2',
      label: '(ohne Name)',
    })
  })

  it('maps an employees array so option values are ids and labels are names', () => {
    const employees = [
      { id: 'a', display_name: 'Alice' },
      { id: 'b', display_name: 'Bob' },
    ]
    const options = employees.map(employeeToOption)
    expect(options.map((o) => o.value)).toEqual(['a', 'b'])
    expect(options.map((o) => o.label)).toEqual(['Alice', 'Bob'])
  })
})

describe('resolveEmployeeName', () => {
  const employees = [
    { id: 'a', display_name: 'Alice' },
    { id: 'b', display_name: null },
  ]

  it('resolves a known id to its display_name', () => {
    expect(resolveEmployeeName(employees, 'a')).toBe('Alice')
  })

  it('returns null for a null/undefined id (no default employee)', () => {
    expect(resolveEmployeeName(employees, null)).toBeNull()
    expect(resolveEmployeeName(employees, undefined)).toBeNull()
  })

  it('returns null when the id is not found in the list', () => {
    expect(resolveEmployeeName(employees, 'missing')).toBeNull()
  })

  it('returns null when the matched employee has no display_name', () => {
    expect(resolveEmployeeName(employees, 'b')).toBeNull()
  })
})

// ─── 4. Required-field key derivation (Pflichtfelder → Neues Feld) ───────────
describe('deriveFieldKey', () => {
  it('slugs the label when no explicit key is given (lowercase, spaces → _)', () => {
    expect(deriveFieldKey('', 'E-Mail Adresse')).toBe('e-mail_adresse')
  })

  it('collapses runs of whitespace into single underscores', () => {
    expect(deriveFieldKey('', 'Letzter   Auftrag')).toBe('letzter_auftrag')
  })

  it('prefers an explicit key over the label', () => {
    expect(deriveFieldKey('custom_key', 'Some Label')).toBe('custom_key')
  })
})
