import { AlertTriangle, Check, Loader2, Upload, Wand2 } from 'lucide-react'
import { useState } from 'react'

import { apiUpload } from '../lib/api'
import { cn } from '../lib/utils'
import { inputCls, labelCls } from './kiki/shared'
import { Modal } from './ui/Modal'

type Entity = 'customers' | 'employees'

interface Target {
  key: string
  label: string
  required?: boolean
}

const TARGETS: Record<Entity, Target[]> = {
  customers: [
    { key: 'full_name', label: 'Name', required: true },
    { key: 'email', label: 'E-Mail' },
    { key: 'phone', label: 'Telefon' },
    { key: 'phone2', label: 'Mobil (2. Nummer)' },
    { key: 'street', label: 'Straße' },
    { key: 'postal_code', label: 'PLZ' },
    { key: 'city', label: 'Ort' },
    { key: 'notes', label: 'Bemerkung / Notizen' },
    { key: 'customer_number', label: 'Kundennummer' },
  ],
  employees: [
    { key: 'display_name', label: 'Name', required: true },
    { key: 'email', label: 'E-Mail' },
    { key: 'access_role', label: 'Rolle' },
    { key: 'activity_area', label: 'Tätigkeitsbereich' },
    { key: 'auto_assign', label: 'Auto-Zuweisung' },
    { key: 'hourly_rate', label: 'Stundensatz' },
    { key: 'vacation_days_per_year', label: 'Urlaubstage/Jahr' },
    { key: 'calendar_color', label: 'Kalenderfarbe (Hex)' },
  ],
}

// Keyword hints to pre-fill the mapping from CSV headers (case-insensitive contains).
const HINTS: Record<string, string[]> = {
  full_name: ['titel+vorname+name', 'name', 'vorname'],
  display_name: ['name'],
  email: ['mail', 'email', 'e-mail'],
  phone: ['telefon', 'phone', 'tel'],
  phone2: ['mobil', 'mobile', 'handy'],
  street: ['strasse', 'straße', 'street', 'str'],
  postal_code: ['plz', 'postleitzahl', 'zip', 'postal'],
  city: ['ort', 'stadt', 'city'],
  notes: ['bemerkung', 'notiz', 'notes', 'comment'],
  customer_number: ['kundennummer', 'kunden-nr', 'kdnr', 'customer_number', 'adressnummer'],
  access_role: ['rolle', 'role'],
  activity_area: ['areas of activity', 'tätigkeit', 'taetigkeit', 'activity'],
  auto_assign: ['auto', 'zuweisung'],
  hourly_rate: ['stundensatz', 'hourly', 'rate'],
  vacation_days_per_year: ['urlaub', 'vacation'],
  calendar_color: ['farbe', 'color', 'kalender'],
}

interface RowResult {
  row: number
  status: string
  reason?: string
  name?: string
  customer_number?: string
}
interface Correction {
  row: number
  action: string
  field_from: string
  field_to: string | null
  value: string
}
interface ImportResult {
  total: number
  imported: number
  skipped_duplicate: number
  errors: number
  corrected?: number
  results: RowResult[]
  corrections?: Correction[]
}
interface ColumnInfo {
  type: string
  confidence: number
  samples: string[]
  mixed_phone?: boolean
}
interface PreviewResp {
  headers: string[]
  columns: Record<string, ColumnInfo>
  suggested_mapping: Record<string, string>
  row_count: number
}

// Detected content type → German label for the column badges.
const TYPE_LABEL: Record<string, string> = {
  email: 'E-Mail',
  mobile: 'Mobilnummer',
  landline: 'Festnetz',
  postal_code: 'PLZ',
  city: 'Ort',
  street: 'Straße',
  person_name: 'Name',
  customer_number: 'Kundennr.',
  free_text: 'Text',
  number: 'Zahl',
  name_or_city: 'Name/Ort',
  empty: 'leer',
}
// Which detected content types are "right" for each target field (green vs amber badge).
const EXPECTED_TYPES: Record<string, string[]> = {
  full_name: ['person_name', 'free_text'],
  email: ['email'],
  phone: ['landline', 'mobile'],
  phone2: ['mobile', 'landline'],
  street: ['street'],
  postal_code: ['postal_code'],
  city: ['city', 'person_name'],
  notes: ['free_text', 'street'],
  customer_number: ['customer_number', 'number'],
}
// Correction action → German sentence for the result report.
const ACTION_LABEL: Record<string, string> = {
  phone_salvaged_from_email: 'Telefonnummer aus E-Mail-Feld gerettet',
  junk_email_dropped: 'Ungültige E-Mail verworfen',
  address_from_notes: 'Adresse aus Notizen übernommen',
}

const STATUS_META: Record<string, { cls: string; label: string }> = {
  imported: { cls: 'text-success', label: 'Importiert' },
  skipped_duplicate: { cls: 'text-warning', label: 'Duplikat' },
  error: { cls: 'text-error', label: 'Fehler' },
}

export function CsvImportModal({
  entity,
  onClose,
  onDone,
}: {
  entity: Entity
  onClose: () => void
  onDone?: () => void
}) {
  const targets = TARGETS[entity]
  const [file, setFile] = useState<File | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [rowCount, setRowCount] = useState(0)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [columns, setColumns] = useState<Record<string, ColumnInfo>>({})
  const [analyzing, setAnalyzing] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Header-name auto-map (instant + fallback if the content analysis is unavailable).
  // Two passes: exact header match first, then substring (hints ≥4 chars) so a wide
  // DATEV export can't bind phone→"Titel" ('tel') or name→"Kurzname" ('name').
  function autoMap(hs: string[]): Record<string, string> {
    const norm = (h: string) => h.toLowerCase().trim()
    const m: Record<string, string> = {}
    const used = new Set<string>()
    for (const t of targets) {
      for (const kw of HINTS[t.key] ?? [t.key]) {
        const found = hs.find((h) => !used.has(h) && norm(h) === kw)
        if (found) {
          m[t.key] = found
          used.add(found)
          break
        }
      }
    }
    for (const t of targets) {
      if (m[t.key]) continue
      const hints = (HINTS[t.key] ?? [t.key]).filter((kw) => kw.length >= 4)
      const found = hs.find((h) => !used.has(h) && hints.some((kw) => norm(h).includes(kw)))
      if (found) {
        m[t.key] = found
        used.add(found)
      }
    }
    return m
  }

  async function onPick(f: File) {
    setError(null)
    setResult(null)
    setColumns({})
    setFile(f)
    const text = await f.text()
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    const first = lines[0] ?? ''
    const delim = first.split(';').length > first.split(',').length ? ';' : ','
    const hs = first
      .split(delim)
      .map((h) => h.trim().replace(/^"|"$/g, ''))
      .filter(Boolean)
    setHeaders(hs)
    setRowCount(Math.max(0, lines.length - 1))
    setMapping(autoMap(hs)) // instant header-based map; refined by content below

    // Content-aware refinement (customers only): the backend samples each column's
    // VALUES, detects its real type, and proposes a mapping where a phone column is
    // never bound to E-Mail/Adresse. Falls back silently to the header-based map.
    if (entity === 'customers') {
      setAnalyzing(true)
      try {
        const fd = new FormData()
        fd.append('file', f)
        const pv = await apiUpload<PreviewResp>('/api/customers/import/preview', fd)
        setColumns(pv.columns ?? {})
        if (pv.row_count) setRowCount(pv.row_count)
        if (pv.suggested_mapping && Object.keys(pv.suggested_mapping).length > 0) {
          setMapping(pv.suggested_mapping)
        }
      } catch {
        /* keep the header-based map */
      } finally {
        setAnalyzing(false)
      }
    }
  }

  const requiredKey = targets.find((t) => t.required)?.key
  const canImport = !!file && !!requiredKey && !!mapping[requiredKey]

  async function doImport() {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('mapping', JSON.stringify(mapping))
      const res = await apiUpload<ImportResult>(`/api/${entity}/import`, fd)
      setResult(res)
      onDone?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onOpenChange={(o) => !o && onClose()}
      title={entity === 'customers' ? 'Kunden-CSV importieren' : 'Mitarbeiter-CSV importieren'}
      widthClass="max-w-2xl"
      footer={
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 rounded-md border border-border bg-alt py-2.5 text-sm font-medium text-body"
          >
            {result ? 'Schließen' : 'Abbrechen'}
          </button>
          {!result && (
            <button
              disabled={!canImport || busy}
              onClick={doImport}
              className="flex-1 inline-flex items-center justify-center gap-2 rounded-md bg-green-primary py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
            >
              <Upload size={15} /> {busy ? 'Importiert…' : `${rowCount} Zeilen importieren`}
            </button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        {error && <div className="rounded-md bg-error-bg px-3 py-2 text-sm text-error">{error}</div>}

        {result ? (
          <ResultView result={result} />
        ) : (
          <>
            <div>
              <div className={labelCls}>CSV-Datei</div>
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => e.target.files?.[0] && onPick(e.target.files[0])}
                className="block w-full text-sm text-body file:mr-3 file:rounded-md file:border-0 file:bg-green-primary file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white"
              />
              {file && (
                <p className="mt-1 text-xs text-muted">
                  {file.name} — {headers.length} Spalten, {rowCount} Zeilen erkannt.
                </p>
              )}
            </div>

            {headers.length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-bold text-text">
                  Spalten zuordnen
                  {analyzing ? (
                    <span className="flex items-center gap-1 text-xs font-normal text-muted">
                      <Loader2 size={12} className="animate-spin" /> Inhalte werden analysiert…
                    </span>
                  ) : (
                    Object.keys(columns).length > 0 && (
                      <span className="flex items-center gap-1 text-xs font-normal text-ai">
                        <Wand2 size={12} /> automatisch erkannt
                      </span>
                    )
                  )}
                </div>
                <div className="space-y-2">
                  {targets.map((t) => {
                    const sel = mapping[t.key]
                    const info = sel ? columns[sel] : undefined
                    const ok = info ? (EXPECTED_TYPES[t.key] ?? []).includes(info.type) : true
                    return (
                      <div key={t.key} className="flex items-center gap-3">
                        <div className="w-40 shrink-0 text-sm text-body">
                          {t.label}
                          {t.required && <span className="text-error"> *</span>}
                        </div>
                        <select
                          value={sel ?? ''}
                          onChange={(e) => setMapping((m) => ({ ...m, [t.key]: e.target.value }))}
                          className={inputCls}
                        >
                          <option value="">— nicht zuordnen —</option>
                          {headers.map((h) => (
                            <option key={h} value={h}>
                              {h}
                            </option>
                          ))}
                        </select>
                        <div className="w-36 shrink-0">
                          {info && (
                            <span
                              title={
                                info.samples?.length
                                  ? `Beispiele: ${info.samples.join('  ·  ')}`
                                  : undefined
                              }
                              className={cn(
                                'inline-flex max-w-full items-center gap-1 truncate rounded-full px-2 py-0.5 text-xs font-medium',
                                ok ? 'bg-success-bg text-success' : 'bg-warning-bg text-warning',
                              )}
                            >
                              {ok ? (
                                <Check size={11} className="shrink-0" />
                              ) : (
                                <AlertTriangle size={11} className="shrink-0" />
                              )}
                              {TYPE_LABEL[info.type] ?? info.type}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
                <p className="mt-2 text-xs text-muted">
                  Spalten werden am Inhalt erkannt — eine Telefonnummer landet nie im E-Mail-
                  oder Adressfeld. Duplikate (E-Mail, Mobilnummer, oder Festnetz + Name) werden
                  übersprungen.{' '}
                  {entity === 'customers'
                    ? 'Importierte Kunden werden als „Stammkunde“ markiert.'
                    : 'Mitarbeiter werden ohne Login angelegt — Einladung anschließend einzeln senden.'}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}

function ResultView({ result }: { result: ImportResult }) {
  const corrections = result.corrections ?? []
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-2 text-center">
        <div className="rounded-md bg-success-bg py-3">
          <div className="text-xl font-bold text-success">{result.imported}</div>
          <div className="text-xs text-muted">Importiert</div>
        </div>
        <div className="rounded-md bg-info-bg py-3">
          <div className="text-xl font-bold text-info">{result.corrected ?? 0}</div>
          <div className="text-xs text-muted">Korrigiert</div>
        </div>
        <div className="rounded-md bg-warning-bg py-3">
          <div className="text-xl font-bold text-warning">{result.skipped_duplicate}</div>
          <div className="text-xs text-muted">Duplikate</div>
        </div>
        <div className="rounded-md bg-error-bg py-3">
          <div className="text-xl font-bold text-error">{result.errors}</div>
          <div className="text-xs text-muted">Fehler</div>
        </div>
      </div>

      {corrections.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-bold text-text">Automatische Korrekturen</div>
          <div className="max-h-40 overflow-y-auto rounded-md border border-border p-2 text-xs">
            {corrections.map((c, i) => (
              <div key={i} className="border-b border-border/50 py-1 last:border-0">
                <span className="text-muted">Zeile {c.row}:</span>{' '}
                {ACTION_LABEL[c.action] ?? c.action}
                {c.field_to ? ` → ${c.field_to}` : ''}{' '}
                <span className="text-faint">({c.value})</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="max-h-64 overflow-y-auto rounded-md border border-border">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-alt text-muted">
            <tr>
              <th className="px-2 py-1">Zeile</th>
              <th className="px-2 py-1">Name</th>
              <th className="px-2 py-1">Status</th>
              <th className="px-2 py-1">Hinweis</th>
            </tr>
          </thead>
          <tbody>
            {result.results.map((r, i) => {
              const meta = STATUS_META[r.status] ?? { cls: 'text-body', label: r.status }
              return (
                <tr key={i} className="border-t border-border">
                  <td className="px-2 py-1 text-muted">{r.row}</td>
                  <td className="px-2 py-1">{r.name ?? '—'}</td>
                  <td className={`px-2 py-1 font-medium ${meta.cls}`}>{meta.label}</td>
                  <td className="px-2 py-1 text-muted">
                    {r.reason ?? (r.customer_number ? `Nr. ${r.customer_number}` : '')}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
