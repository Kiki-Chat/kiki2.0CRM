import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { apiFetch } from '../lib/adminApi'

interface OrgDetail {
  id: string
  heykiki_org_id: string | null
  name: string | null
  email: string | null
  phone_number: string | null
  elevenlabs_agent_id: string | null
  disabled_at: string | null
  created_at: string
}

interface CreateOrgResponse {
  org_id: string
  admin_user_id: string
  heykiki_org_id: string
}

/**
 * Create-or-edit screen for an organization. Routes:
 *  - /admin/orgs/new  → create form → POST /api/super-admin/orgs (wraps provision_org)
 *                        → neutral success card with the new identifiers.
 *  - /admin/orgs/:id  → edit form (4 master-data fields) → PATCH /orgs/{id}.
 *
 * B.6 (2026-05-27): the per-org `org_secret` panel was removed. That secret is
 * system-level (used by the ElevenLabs post-call webhook handler), NOT
 * per-customer — identification happens via agent_id + caller phone_number.
 * The previous "save this now / nur einmal sichtbar" panel was misleading.
 */
export function AdminOrgFormPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isNew = !id

  // CREATE fields
  const [heykikiOrgId, setHeykikiOrgId] = useState('')
  const [orgName, setOrgName] = useState('')
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [elevenlabsAgentId, setElevenlabsAgentId] = useState('')
  const [adminName, setAdminName] = useState('')
  const [contactEmail, setContactEmail] = useState('')

  // EDIT fields
  const [editName, setEditName] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [editPhone, setEditPhone] = useState('')
  const [editAgentId, setEditAgentId] = useState('')

  const [createResult, setCreateResult] = useState<CreateOrgResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const detailQuery = useQuery({
    queryKey: ['admin', 'org', id],
    queryFn: () => apiFetch<OrgDetail>(`/api/super-admin/orgs/${id}`),
    enabled: !isNew,
  })

  useEffect(() => {
    if (detailQuery.data) {
      setEditName(detailQuery.data.name ?? '')
      setEditEmail(detailQuery.data.email ?? '')
      setEditPhone(detailQuery.data.phone_number ?? '')
      setEditAgentId(detailQuery.data.elevenlabs_agent_id ?? '')
    }
  }, [detailQuery.data])

  const resetCreateForm = () => {
    setHeykikiOrgId('')
    setOrgName('')
    setLoginEmail('')
    setLoginPassword('')
    setElevenlabsAgentId('')
    setAdminName('')
    setContactEmail('')
    setCreateResult(null)
    setError(null)
  }

  const createMut = useMutation({
    mutationFn: () =>
      apiFetch<CreateOrgResponse>('/api/super-admin/orgs', {
        method: 'POST',
        body: JSON.stringify({
          heykikiOrgId,
          orgName,
          loginEmail,
          loginPassword,
          elevenlabsAgentId,
          adminName: adminName || undefined,
          contactEmail: contactEmail || undefined,
        }),
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['admin', 'orgs'] })
      qc.invalidateQueries({ queryKey: ['admin', 'orgs-stats'] })
      setCreateResult(data)
      setError(null)
    },
    onError: (e: Error) => setError(e.message),
  })

  const editMut = useMutation({
    mutationFn: () =>
      apiFetch<OrgDetail>(`/api/super-admin/orgs/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: editName,
          email: editEmail || null,
          phone_number: editPhone || null,
          elevenlabs_agent_id: editAgentId,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'orgs'] })
      qc.invalidateQueries({ queryKey: ['admin', 'org', id] })
      navigate('/admin/orgs')
    },
    onError: (e: Error) => setError(e.message),
  })

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (isNew) createMut.mutate()
    else editMut.mutate()
  }

  if (isNew && createResult) {
    return (
      <div className="mx-auto max-w-2xl space-y-5">
        <header>
          <h1 className="text-2xl font-bold text-slate-100">Organisation angelegt</h1>
          <p className="mt-1 text-sm text-slate-400">
            Die neue Organisation wurde erstellt und ist sofort einsatzbereit.
          </p>
        </header>
        <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-300">
            <CheckCircle2 size={16} /> Anlage erfolgreich
          </div>
          <div className="grid grid-cols-[160px,1fr] gap-y-2 text-sm">
            <div className="text-slate-500">org_id:</div>
            <div className="font-mono text-xs text-slate-200">{createResult.org_id}</div>
            <div className="text-slate-500">heykiki_org_id:</div>
            <div className="font-mono text-xs text-slate-200">{createResult.heykiki_org_id}</div>
            <div className="text-slate-500">admin_user_id:</div>
            <div className="font-mono text-xs text-slate-200">{createResult.admin_user_id}</div>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button
            onClick={resetCreateForm}
            className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
          >
            Weitere Org anlegen
          </button>
          <button
            onClick={() => navigate('/admin/orgs')}
            className="rounded-md bg-amber-500 px-5 py-2 text-sm font-semibold text-slate-950 hover:bg-amber-400"
          >
            Zur Org-Liste
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header>
        <button
          onClick={() => navigate('/admin/orgs')}
          className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-400 hover:text-slate-200"
        >
          <ArrowLeft size={13} /> Zurück zur Liste
        </button>
        <h1 className="text-2xl font-bold text-slate-100">
          {isNew ? 'Neue Organisation' : `Bearbeiten: ${detailQuery.data?.name ?? '…'}`}
        </h1>
      </header>

      {error && (
        <div className="rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <form
        onSubmit={onSubmit}
        className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-6"
      >
        {isNew ? (
          <>
            <Field label="Organisationsname *" value={orgName} onChange={setOrgName} required placeholder="Murdock Law GmbH" />
            <Field
              label="heykiki_org_id *"
              value={heykikiOrgId}
              onChange={setHeykikiOrgId}
              required
              placeholder="kiki-customer-001"
              mono
              help="Eindeutige slug-style ID — nicht änderbar nach dem Anlegen."
            />
            <Field
              label="ElevenLabs Agent ID *"
              value={elevenlabsAgentId}
              onChange={setElevenlabsAgentId}
              required
              placeholder="agent_…"
              mono
              help="NICHT agent_7201… (Produktion)."
            />
            <div className="my-2 h-px bg-slate-800" />
            <Field label="Admin Login-E-Mail *" value={loginEmail} onChange={setLoginEmail} required type="email" placeholder="admin@firma.de" />
            <Field label="Admin Login-Passwort *" value={loginPassword} onChange={setLoginPassword} required type="password" placeholder="mind. 8 Zeichen" help="Mindestens 8 Zeichen. Wird per E-Mail an den Admin mitgeteilt." />
            <Field label="Admin-Name" value={adminName} onChange={setAdminName} placeholder="Max Mustermann" />
            <Field label="Kontakt-E-Mail (optional)" value={contactEmail} onChange={setContactEmail} type="email" placeholder="kontakt@firma.de" help="Falls leer: Login-E-Mail." />
          </>
        ) : (
          <>
            <Field label="Name *" value={editName} onChange={setEditName} required />
            <Field label="Kontakt-E-Mail" value={editEmail} onChange={setEditEmail} type="email" />
            <Field label="Telefonnummer" value={editPhone} onChange={setEditPhone} />
            <Field label="ElevenLabs Agent ID *" value={editAgentId} onChange={setEditAgentId} required mono help="NICHT agent_7201… (Produktion)." />
          </>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={() => navigate('/admin/orgs')}
            className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700"
          >
            Abbrechen
          </button>
          <button
            type="submit"
            disabled={createMut.isPending || editMut.isPending}
            className="rounded-md bg-amber-500 px-6 py-2 text-sm font-semibold text-slate-950 hover:bg-amber-400 disabled:opacity-50"
          >
            {createMut.isPending || editMut.isPending ? 'Speichert…' : isNew ? 'Organisation anlegen' : 'Speichern'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  required,
  placeholder,
  type = 'text',
  mono = false,
  help,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  required?: boolean
  placeholder?: string
  type?: string
  mono?: boolean
  help?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-400">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        placeholder={placeholder}
        className={`w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-amber-500 ${
          mono ? 'font-mono text-xs' : ''
        }`}
      />
      {help && <p className="mt-1 text-xs text-slate-500">{help}</p>}
    </label>
  )
}
