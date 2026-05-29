import { Upload } from 'lucide-react'
import { useState } from 'react'

import { apiUpload } from '../lib/api'
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
interface ImportResult {
  total: number
  imported: number
  skipped_duplicate: number
  errors: number
  results: RowResult[]
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
  const [result, setResult] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onPick(f: File) {
    setError(null)
    setResult(null)
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
    const m: Record<string, string> = {}
    for (const t of targets) {
      const hints = HINTS[t.key] ?? [t.key]
      const found = hs.find((h) => hints.some((kw) => h.toLowerCase().includes(kw)))
      if (found) m[t.key] = found
    }
    setMapping(m)
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
                <div className="mb-2 text-sm font-bold text-text">Spalten zuordnen</div>
                <div className="space-y-2">
                  {targets.map((t) => (
                    <div key={t.key} className="flex items-center gap-3">
                      <div className="w-44 shrink-0 text-sm text-body">
                        {t.label}
                        {t.required && <span className="text-error"> *</span>}
                      </div>
                      <select
                        value={mapping[t.key] ?? ''}
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
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-xs text-muted">
                  Duplikate (gleiche E-Mail/Telefon) werden übersprungen, nie überschrieben.{' '}
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
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-md bg-success-bg py-3">
          <div className="text-xl font-bold text-success">{result.imported}</div>
          <div className="text-xs text-muted">Importiert</div>
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
