import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Eye, EyeOff, Lock, LogOut } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useAuth } from '../auth/AuthProvider'
import { apiFetch } from '../lib/api'
import { useTheme } from '../lib/theme'
import { cn, initials } from '../lib/utils'
import { Modal } from './ui/Modal'

interface Me {
  full_name: string | null
  email: string | null
  role: string | null
  avatar_url: string | null
}

const inputCls = 'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'

export function PersonalSettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { signOut } = useAuth()
  const { theme, toggle } = useTheme()

  const [name, setName] = useState('')
  const [pwOpen, setPwOpen] = useState(false)
  const [cur, setCur] = useState('')
  const [nw, setNw] = useState('')
  const [conf, setConf] = useState('')
  const [showCur, setShowCur] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [pwError, setPwError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 3000) }

  const { data: me } = useQuery({
    queryKey: ['users-me'],
    queryFn: () => apiFetch<Me>('/api/users/me'),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  useEffect(() => { if (me) setName(me.full_name ?? '') }, [me])

  const saveProfile = useMutation({
    mutationFn: () => apiFetch('/api/users/me', { method: 'PATCH', body: JSON.stringify({ full_name: name }) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['users-me'] }); onClose() },
  })
  const changePw = useMutation({
    mutationFn: () => apiFetch('/api/users/me/change-password', { method: 'POST', body: JSON.stringify({ current_password: cur, new_password: nw }) }),
    onSuccess: () => { setPwOpen(false); setCur(''); setNw(''); setConf(''); setPwError(null); flash('Passwort geändert.') },
    onError: (e: Error) => setPwError(e.message || 'Passwort konnte nicht geändert werden.'),
  })

  const submitPw = () => {
    setPwError(null)
    if (nw.length < 8) { setPwError('Neues Passwort muss mindestens 8 Zeichen haben.'); return }
    if (nw !== conf) { setPwError('Die neuen Passwörter stimmen nicht überein.'); return }
    changePw.mutate()
  }
  const close = () => { setPwOpen(false); setCur(''); setNw(''); setConf(''); setPwError(null); onClose() }

  return (
    <Modal
      open={open}
      onOpenChange={(o) => !o && close()}
      title="Persönliche Einstellungen"
      widthClass="max-w-[520px]"
      footer={
        <div className="flex items-center justify-between">
          <button onClick={() => signOut()} className="inline-flex items-center gap-1.5 text-sm font-medium text-error hover:underline"><LogOut size={15} /> Abmelden</button>
          <div className="flex gap-3">
            <button onClick={close} className="rounded-md border border-border bg-alt px-4 py-2 text-sm font-medium text-body">Abbrechen</button>
            <button onClick={() => saveProfile.mutate()} disabled={saveProfile.isPending} className="rounded-md bg-green-primary px-5 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{saveProfile.isPending ? 'Speichert…' : 'Speichern'}</button>
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        {toast && <div className="rounded-md bg-green-tint-50 px-3 py-2 text-sm font-medium text-green-deep">{toast}</div>}

        {/* Profil */}
        <section>
          <h3 className="mb-3 text-xs font-bold uppercase tracking-wide text-muted">Profil</h3>
          <div className="mb-4 flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-green-tint-200 text-lg font-bold text-green-deep">{initials(name || me?.email || '?')}</div>
            <span title="In Kürze verfügbar" className="cursor-not-allowed text-sm font-medium text-faint">Bild hochladen</span>
            {/* TODO: avatar upload out of scope this sprint. */}
          </div>
          <div className="space-y-3">
            <div>
              <div className="mb-1 text-xs font-semibold text-body">Vollständiger Name *</div>
              <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-body">E-Mail</div>
              <div className="relative">
                <input value={me?.email ?? ''} readOnly className={cn(inputCls, 'cursor-not-allowed pr-9 text-muted')} />
                <Lock size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-faint" />
              </div>
              <p className="mt-1 text-xs text-muted">E-Mail kann nicht geändert werden.</p>
            </div>
          </div>
        </section>

        {/* Darstellung */}
        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Darstellung</h3>
          <label className="flex items-center justify-between">
            <span className="text-sm text-text">Dunkles Design</span>
            <button onClick={toggle} className={cn('relative h-6 w-11 shrink-0 rounded-full transition', theme === 'dark' ? 'bg-green-primary' : 'bg-border')}>
              <span className={cn('absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all', theme === 'dark' ? 'left-[22px]' : 'left-0.5')} />
            </button>
          </label>
        </section>

        {/* Passwort ändern */}
        <section>
          <div className="rounded-lg border border-border">
            <button onClick={() => setPwOpen((o) => !o)} className="flex w-full items-center justify-between px-4 py-3 text-sm font-semibold text-text">
              Passwort ändern <ChevronDown size={16} className={cn('text-muted transition-transform', pwOpen && 'rotate-180')} />
            </button>
            {pwOpen && (
              <div className="space-y-3 border-t border-border p-4">
                <PwInput label="Aktuelles Passwort" value={cur} onChange={setCur} show={showCur} onToggle={() => setShowCur((s) => !s)} />
                {pwError && <p className="text-xs font-medium text-error">{pwError}</p>}
                <PwInput label="Neues Passwort" value={nw} onChange={setNw} show={showNew} onToggle={() => setShowNew((s) => !s)} />
                <PwInput label="Passwort bestätigen" value={conf} onChange={setConf} show={showNew} onToggle={() => setShowNew((s) => !s)} />
                <button onClick={submitPw} disabled={changePw.isPending} className="rounded-md bg-green-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">{changePw.isPending ? 'Ändert…' : 'Passwort ändern'}</button>
              </div>
            )}
          </div>
        </section>
      </div>
    </Modal>
  )
}

function PwInput({ label, value, onChange, show, onToggle }: { label: string; value: string; onChange: (v: string) => void; show: boolean; onToggle: () => void }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-body">{label}</div>
      <div className="relative">
        <input type={show ? 'text' : 'password'} value={value} onChange={(e) => onChange(e.target.value)} className={cn(inputCls, 'pr-9')} />
        <button onClick={onToggle} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted">{show ? <EyeOff size={15} /> : <Eye size={15} />}</button>
      </div>
    </div>
  )
}
