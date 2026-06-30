// Funnel constants. TRADES mirrors backend app/schemas/onboarding.py TRADES.
export const TRADES: string[] = [
  'Dachdecker',
  'Zimmerer',
  'Tischler',
  'Hausmeisterservice',
  'Gebäudereiniger',
  'KFZ-Mechaniker',
  'SHK-Installateure',
  'Elektrotechniker',
  'Maler und Lackierer',
  'Klempner',
  'Fliesenleger',
  'Maurer',
  'Garten- und Landschaftsbauer',
  'Solarteur',
  'Schlosser',
  'Isolierer',
  'Raumausstatter',
  'Hausverwalter',
]

// Self-serve tiers shown in the funnel, in order. 'Kiki Legacy' is never offered.
export const PLAN_ORDER = ['Kiki Basis', 'Kiki Pro', 'Kiki Enterprise'] as const
export const RECOMMENDED_PLAN = 'Kiki Pro'

// Curated feature bullets per tier (minutes/seats are rendered from the live
// PlanOption; these are the cumulative capability highlights).
export const PLAN_FEATURES: Record<string, string[]> = {
  'Kiki Basis': [
    'Kiki qualifiziert deine Anrufe',
    'Kontaktverwaltung',
    'Geschäftszeiten & Begrüßungen',
    'Unbegrenzte Assistenten',
  ],
  'Kiki Pro': [
    'Alles aus Basis',
    'Vorgänge & Aufträge',
    'Planungstafel',
    'Kalender & Termine',
    'Automatische KI-Notizen',
  ],
  'Kiki Enterprise': [
    'Alles aus Pro',
    'Projekte',
    'Finanzen: Angebote & Rechnungen',
    'Artikel/Katalog & ERP',
    'API-Zugang',
  ],
}

export const PLAN_TAGLINE: Record<string, string> = {
  'Kiki Basis': 'Für den Einstieg',
  'Kiki Pro': 'Für wachsende Betriebe',
  'Kiki Enterprise': 'Für hohe Anrufvolumen',
}

export const CALENDLY_URL =
  'https://calendly.com/kiki-chat/einrichtung-der-testphase-von-heykiki?month=2026-06'

export const ONBOARDING_TOKEN_KEY = 'kiki_onb_token'
export const ONBOARDING_COMPANY_KEY = 'kiki_onb_company'
