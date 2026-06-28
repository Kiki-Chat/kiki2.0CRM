// Frontend mirror of the backend entitlement matrix (app/services/entitlements.py).
// Drives the locked-menu liquid-glass paywall + upgrade CTA. The org's GRANTED feature keys
// come live from /api/me (`features`); this file only holds the display copy + which
// plan unlocks each feature. Keep in sync with the backend matrix.

export interface FeatureMeta {
  key: string
  label: string
  minPlan: string // lowest self-serve plan that unlocks it
  pitch: string[] // what the customer gets — shown on the locked panel
}

export const FEATURE_META: Record<string, FeatureMeta> = {
  cases: {
    key: 'cases',
    label: 'Vorgänge',
    minPlan: 'Kiki Pro',
    pitch: [
      'Anfragen aus Anrufen automatisch zu Vorgängen bündeln',
      'Status & kompletter Verlauf je Kunde an einem Ort',
      'Aufträge & Techniker-Disposition direkt aus dem Vorgang',
    ],
  },
  calendar: {
    key: 'calendar',
    label: 'Kalender & Terminverwaltung',
    minPlan: 'Kiki Pro',
    pitch: [
      'Termine direkt aus dem Anruf anlegen lassen',
      'Automatische Terminvorschläge durch Kiki',
      'Auslastung deiner Mitarbeiter auf einen Blick',
    ],
  },
  planning: {
    key: 'planning',
    label: 'Planungstafel',
    minPlan: 'Kiki Pro',
    pitch: [
      'Aufträge visuell per Drag & Drop einplanen',
      'Disposition über Tage und Mitarbeiter hinweg',
      'Engpässe früh erkennen',
    ],
  },
  projects: {
    key: 'projects',
    label: 'Projekte',
    minPlan: 'Kiki Enterprise',
    pitch: [
      'Mehrere Vorgänge zu einem Projekt zusammenfassen',
      'Eigener Projekt-Workspace mit Fortschritt',
      'Den Überblick über große Aufträge behalten',
    ],
  },
  finance: {
    key: 'finance',
    label: 'Finanzen',
    minPlan: 'Kiki Enterprise',
    pitch: [
      'Angebote erstellen & per E-Mail versenden',
      'Rechnungen schreiben & Zahlungsstatus verfolgen',
      'Artikel- & Leistungskatalog für schnelle Angebote',
    ],
  },
}

export const shortPlanName = (t: string | null | undefined) => (t ?? '').replace(/^Kiki\s+/, '')

/** Mirror of backend PLAN_FEATURES — used to refresh sidebar locks instantly after a plan switch. */
const PLAN_FEATURES: Record<string, readonly string[]> = {
  'Kiki Basis': [],
  'Kiki Legacy': ['cases'],
  'Kiki Pro': ['cases', 'calendar', 'planning'],
  'Kiki Enterprise': ['cases', 'calendar', 'planning', 'projects', 'finance'],
}

export function featuresForPlan(planTitle: string | null | undefined): string[] {
  return [...(PLAN_FEATURES[planTitle ?? ''] ?? [])]
}
