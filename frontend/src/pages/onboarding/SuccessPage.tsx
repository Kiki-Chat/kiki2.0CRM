import { useEffect } from 'react'
import { CheckCircle2, Mail } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { OnboardingLayout } from './OnboardingLayout'
import { ONBOARDING_COMPANY_KEY, ONBOARDING_TOKEN_KEY } from './constants'

export function SuccessPage() {
  useEffect(() => {
    // Funnel complete — clear the lead token so a back-nav can't re-checkout.
    sessionStorage.removeItem(ONBOARDING_TOKEN_KEY)
    sessionStorage.removeItem(ONBOARDING_COMPANY_KEY)
  }, [])

  return (
    <OnboardingLayout step={3}>
      <div className="text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-tint-100">
          <CheckCircle2 size={34} className="text-green-primary" />
        </div>
        <h1 className="mt-5 text-2xl font-bold text-text">Zahlung bestätigt!</h1>
        <p className="mt-2 text-sm text-muted">
          Vielen Dank. Wir richten gerade dein HeyKiki-Konto ein – deine persönliche
          KI-Telefonistin, deine Rufnummer und dein CRM.
        </p>

        <div className="mt-6 flex items-start gap-3 rounded-lg border border-border bg-surface p-4 text-left">
          <Mail size={18} className="mt-0.5 shrink-0 text-green-deep" />
          <p className="text-sm text-body">
            In wenigen Minuten erhältst du eine E-Mail mit deinen Login-Daten und deiner
            Kiki-Rufnummer. Deine Rechnung kommt separat von Stripe.
          </p>
        </div>

        <a href="/login" className="mt-6 block">
          <Button variant="primary" className="w-full">
            Zum Login
          </Button>
        </a>
        <p className="mt-3 text-xs text-muted">
          Noch Fragen? Schreib uns an{' '}
          <a href="mailto:info@kikichat.de" className="text-green-deep underline-offset-2 hover:underline">
            info@kikichat.de
          </a>
        </p>
      </div>
    </OnboardingLayout>
  )
}
