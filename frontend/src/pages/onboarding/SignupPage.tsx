import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Check, Eye, EyeOff, Loader2 } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { cn } from '../../lib/utils'
import { checkOnboardingEmail, startOnboarding } from '../../lib/onboardingApi'
import { OnboardingLayout } from './OnboardingLayout'
import { PhoneField } from './PhoneField'
import { ONBOARDING_COMPANY_KEY, ONBOARDING_TOKEN_KEY, TRADES } from './constants'

const fieldCls =
  'w-full rounded-md border border-border bg-alt px-3 py-2.5 text-sm text-text outline-none focus:border-green-primary'
const labelCls = 'mb-1.5 block text-sm font-medium text-body'

export function SignupPage() {
  const navigate = useNavigate()
  const [trade, setTrade] = useState('')
  const [contactName, setContactName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [email, setEmail] = useState('')
  const [emailState, setEmailState] = useState<'idle' | 'checking' | 'free' | 'taken'>('idle')
  const [phone, setPhone] = useState<{ e164: string; valid: boolean }>({ e164: '', valid: false })
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleEmailBlur() {
    const value = email.trim()
    if (!value || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) {
      setEmailState('idle')
      return
    }
    setEmailState('checking')
    try {
      const { available } = await checkOnboardingEmail(value)
      setEmailState(available ? 'free' : 'taken')
    } catch {
      setEmailState('idle') // never block on a check hiccup; backend re-validates on start
    }
  }

  const pwTooShort = password.length > 0 && password.length < 8
  const pwMismatch = confirm.length > 0 && confirm !== password

  function validate(): string | null {
    if (!trade) return 'Bitte wähle dein Gewerk aus.'
    if (!contactName.trim()) return 'Bitte gib deinen Namen ein.'
    if (!companyName.trim()) return 'Bitte gib deinen Firmennamen ein.'
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return 'Bitte gib eine gültige E-Mail an.'
    if (emailState === 'taken') return 'Diese E-Mail ist bereits registriert.'
    if (!phone.valid) return 'Bitte gib eine gültige Telefonnummer ein.'
    if (password.length < 8) return 'Das Passwort muss mindestens 8 Zeichen lang sein.'
    if (password !== confirm) return 'Die Passwörter stimmen nicht überein.'
    return null
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const v = validate()
    if (v) {
      setError(v)
      return
    }
    setError(null)
    setBusy(true)
    try {
      const { token } = await startOnboarding({
        trade,
        contact_name: contactName.trim(),
        company_name: companyName.trim(),
        email: email.trim(),
        phone: phone.e164,
        password,
      })
      sessionStorage.setItem(ONBOARDING_TOKEN_KEY, token)
      sessionStorage.setItem(ONBOARDING_COMPANY_KEY, companyName.trim())
      navigate('/onboarding/tarif')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Registrierung fehlgeschlagen.'
      setError(msg)
      if (/registriert|exists|409/i.test(msg)) setEmailState('taken')
    } finally {
      setBusy(false)
    }
  }

  return (
    <OnboardingLayout step={1}>
      <h1 className="text-2xl font-bold text-text">Konto erstellen</h1>
      <p className="mt-1 text-sm text-muted">In wenigen Schritten startklar mit deiner KI-Telefonistin.</p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <div>
          <label className={labelCls}>Wähle dein Gewerk aus</label>
          <select value={trade} onChange={(e) => setTrade(e.target.value)} className={cn(fieldCls, !trade && 'text-muted')}>
            <option value="">Bitte auswählen…</option>
            {TRADES.map((t) => (
              <option key={t} value={t} className="text-text">
                {t}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={labelCls}>Wie lautet dein vollständiger Name?</label>
          <input value={contactName} onChange={(e) => setContactName(e.target.value)} className={fieldCls} autoComplete="name" />
        </div>

        <div>
          <label className={labelCls}>Wie lautet dein Firmenname?</label>
          <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} className={fieldCls} autoComplete="organization" />
        </div>

        <div>
          <label className={labelCls}>Wie lautet deine E-Mail-Adresse?</label>
          <div className="relative">
            <input
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value)
                setEmailState('idle')
              }}
              onBlur={handleEmailBlur}
              className={cn(fieldCls, emailState === 'taken' && 'border-error focus:border-error')}
              autoComplete="email"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2">
              {emailState === 'checking' && <Loader2 size={15} className="animate-spin text-muted" />}
              {emailState === 'free' && <Check size={15} className="text-green-primary" />}
              {emailState === 'taken' && <AlertCircle size={15} className="text-error" />}
            </span>
          </div>
          {emailState === 'taken' && (
            <p className="mt-1 text-xs text-error">Diese E-Mail ist bereits registriert. Schon ein Konto? <a href="/login" className="underline">Anmelden</a></p>
          )}
        </div>

        <div>
          <label className={labelCls}>Wie lautet deine Telefonnummer?</label>
          <PhoneField onChange={setPhone} />
        </div>

        <div>
          <label className={labelCls}>Passwort wählen</label>
          <div className="relative">
            <input
              type={showPw ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={cn(fieldCls, 'pr-10', pwTooShort && 'border-error focus:border-error')}
              autoComplete="new-password"
            />
            <button
              type="button"
              onClick={() => setShowPw((s) => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-body"
              aria-label={showPw ? 'Passwort verbergen' : 'Passwort anzeigen'}
            >
              {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <p className={cn('mt-1 text-xs', pwTooShort ? 'text-error' : 'text-muted')}>
            Mindestens 8 Zeichen.
          </p>
        </div>

        <div>
          <label className={labelCls}>Passwort bestätigen</label>
          <input
            type={showPw ? 'text' : 'password'}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={cn(fieldCls, pwMismatch && 'border-error focus:border-error')}
            autoComplete="new-password"
          />
          {pwMismatch && <p className="mt-1 text-xs text-error">Die Passwörter stimmen nicht überein.</p>}
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-md border border-error/30 bg-error-bg/40 p-3 text-sm text-error">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <Button type="submit" variant="primary" disabled={busy} className="w-full">
          {busy ? 'Wird erstellt…' : 'Weiter zur Tarifauswahl'}
        </Button>

        <p className="text-center text-xs text-muted">
          Schon ein Konto?{' '}
          <a href="/login" className="text-green-deep underline-offset-2 hover:underline">
            Anmelden
          </a>
        </p>
      </form>
    </OnboardingLayout>
  )
}
