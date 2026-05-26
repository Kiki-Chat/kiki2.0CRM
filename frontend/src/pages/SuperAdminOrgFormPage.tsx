import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ShieldAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { apiFetch } from '../lib/api'

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

interface ProvisionResponse {
  org_id: string
  user_id: string
  heykiki_org_id: string
  org_secret: string
}

export function SuperAdminOrgFormPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const isNew = !id

  // Form state — different fields for create vs edit.
  // CREATE fields (camelCase, matching ProvisionRequest aliases):
  const [heykikiOrgId, setHeykikiOrgId] = useState('')
  const [orgName, setOrgName] = useState('')
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [elevenlabsAgentId, setElevenlabsAgentId] = useState('')
  const [adminName, setAdminName] = useState('')
  const [contactEmail, setContactEmail] = useState('')

  // EDIT fields:
  const [editName, setEditName] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [editPhone, setEditPhone] = useState('')
  const [editAgentId, setEditAgentId] = useState('')

  const [secretResult, setSecretResult] = useState<ProvisionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const detailQuery = useQuery({
    queryKey: ['super-admin', 'org', id],
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

  const createMut = useMutation({
    mutationFn: () =>
      apiFetch<ProvisionResponse>('/api/super-admin/orgs', {
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
      qc.invalidateQueries({ queryKey: ['super-admin', 'orgs'] })
      setSecretResult(data)
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
      qc.invalidateQueries({ queryKey: ['super-admin', 'orgs'] })
      qc.invalidateQueries({ queryKey: ['super-admin', 'org', id] })
      navigate('/super-admin/orgs')
    },
    onError: (e: Error) => setError(e.message),
  })

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (isNew) createMut.mutate()
    else editMut.mutate()
  }

  // Render the success panel after a successful create — surfaces the
  // org_secret exactly once for super-admin to capture.
  if (isNew && secretResult) {
    return (
      <div className="mx-auto max-w-2xl space-y-5 p-6">
        <header>
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-ai">
            <ShieldAlert size={13} /> Super-Admin
          </div>
          <h1 className="mt-1 text-xl font-bold text-text">Organisation angelegt</h1>
        </header>
        <div className="rounded-xl border border-warning/30 bg-warning-bg/40 p-4 text-sm">
          <div className="font-bold text-warning">⚠ org_secret nur einmal sichtbar</div>
          <p className="mt-1 text-body">
            Notieren Sie das folgende Secret jetzt — es wird nicht erneut angezeigt. Es wird für N8N → Backend Post-Call-Webhooks benötigt.
          </p>
          <div className="mt-3 break-all rounded-md bg-surface p-3 font-mono text-xs">
            {secretResult.org_secret}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4 text-sm">
          <div className="grid grid-cols-[140px,1fr] gap-y-2">
            <div className="text-muted">org_id:</div><div className="font-mono text-xs">{secretResult.org_id}</div>
            <div className="text-muted">heykiki_org_id:</div><div className="font-mono text-xs">{secretResult.heykiki_org_id}</div>
            <div className="text-muted">admin user_id:</div><div className="font-mono text-xs">{secretResult.user_id}</div>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button
            onClick={() => navigate('/super-admin/orgs')}
            className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
          >
            Zur Liste
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5 p-6">
      <header>
        <button
          onClick={() => navigate('/super-admin/orgs')}
          className="mb-2 flex items-center gap-1 text-xs font-medium text-muted hover:text-body"
        >
          <ArrowLeft size={13} /> Zurück zur Liste
        </button>
        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-ai">
          <ShieldAlert size={13} /> Super-Admin
        </div>
        <h1 className="mt-1 text-xl font-bold text-text">
          {isNew ? 'Neue Organisation' : `Bearbeiten: ${detailQuery.data?.name ?? '…'}`}
        </h1>
      </header>

      {error && (
        <div className="rounded-md border border-error/30 bg-error-bg/40 px-3 py-2 text-sm text-error">
          {error}
        </div>
      )}

      <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-border bg-surface p-6">
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
              help="Der vorab in ElevenLabs angelegte Agent dieser Organisation. NICHT agent_7201… (Produktion)."
            />
            <div className="my-2 h-px bg-border" />
            <Field label="Admin Login-E-Mail *" value={loginEmail} onChange={setLoginEmail} required type="email" placeholder="admin@firma.de" />
            <Field label="Admin Login-Passwort *" value={loginPassword} onChange={setLoginPassword} required type="password" placeholder="mind. 8 Zeichen" help="Mindestens 8 Zeichen. Wird per E-Mail an den Admin mitgeteilt." />
            <Field label="Admin-Name" value={adminName} onChange={setAdminName} placeholder="Max Mustermann" />
            <Field label="Kontakt-E-Mail (optional)" value={contactEmail} onChange={setContactEmail} type="email" placeholder="kontakt@firma.de" help="Wird verwendet für Rechnungen / Erinnerungen. Falls leer: Login-E-Mail." />
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
            onClick={() => navigate('/super-admin/orgs')}
            className="rounded-md border border-border bg-surface px-4 py-2 text-sm font-medium text-body hover:bg-alt"
          >
            Abbrechen
          </button>
          <button
            type="submit"
            disabled={createMut.isPending || editMut.isPending}
            className="rounded-md bg-green-primary px-6 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
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
      <span className="mb-1 block text-sm font-medium text-body">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        placeholder={placeholder}
        className={`w-full rounded-md border border-border bg-alt px-3 py-2 text-sm outline-none focus:border-green-primary ${
          mono ? 'font-mono text-xs' : ''
        }`}
      />
      {help && <p className="mt-1 text-xs text-muted">{help}</p>}
    </label>
  )
}
