import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink, Info, PhoneForwarded, Smartphone } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Card, GroupLabel } from '../components/kiki/shared'
import { apiFetch } from '../lib/api'
import { KZ, KZ_STALE, type KzOverview } from '../lib/kikiApi'

// Static German guide for setting up call forwarding from the customer's
// existing business number to their HeyKiki number. Linked from
// Kiki-Zentrale → Telefon ("Anleitung").

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-md border border-border bg-alt px-1.5 py-0.5 font-mono text-sm font-semibold text-text">
      {children}
    </code>
  )
}

function Step({ n, children }: { n: number; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-green-tint-100 text-xs font-bold text-green-deep">
        {n}
      </span>
      <span className="pt-0.5">{children}</span>
    </li>
  )
}

const PROVIDERS: { label: string; href: string }[] = [
  { label: 'Telekom', href: 'https://www.telekom.de/hilfe/mobilfunk/telefonieren-sms-mms/anrufweiterleitungen' },
  { label: 'Vodafone', href: 'https://www.vodafone.de/hilfe/anrufweiterleitung.html' },
  { label: 'O2', href: 'https://www.o2business.de/magazin/rufumleitung-festnetz-auf-handy/' },
]

export function RufumleitungGuidePage() {
  const navigate = useNavigate()
  // Pull the org's assigned HeyKiki number so the codes show the real target
  // instead of an "IHRE-HEYKIKI-NUMMER" placeholder. Shares the cache key with
  // Kiki-Zentrale so it's usually already loaded.
  const { data } = useQuery({
    queryKey: ['kiki-zentrale'],
    queryFn: () => apiFetch<KzOverview>(KZ),
    staleTime: KZ_STALE,
  })
  const heyKiki = data?.phone_number?.trim() || null
  const dial = heyKiki ? heyKiki.replace(/\s+/g, '') : 'IHRE-HEYKIKI-NUMMER'
  const numHint = heyKiki ? <> (<Code>{heyKiki}</Code>)</> : null

  return (
    <div className="mx-auto max-w-3xl p-8">
      <div className="mb-6 flex items-center gap-3">
        <button onClick={() => navigate('/kiki-zentrale/telefon')} className="rounded-md p-1.5 text-muted hover:bg-alt">
          <ArrowLeft size={20} />
        </button>
        <PhoneForwarded size={26} className="text-green-primary" />
        <h1 className="text-2xl font-bold text-text">Rufumleitung einrichten</h1>
      </div>

      <p className="mb-6 text-sm text-body">
        Damit Kiki deine Anrufe entgegennimmt, leite deine bestehende Geschäftsnummer auf deine
        HeyKiki-Nummer um. Eingehende Anrufe landen dann automatisch bei Kiki — Ihre gewohnte Nummer
        bleibt unverändert und Sie müssen sie nirgends ändern.
      </p>

      <div className="mb-6 flex gap-3 rounded-lg border border-info/30 bg-info-bg px-4 py-3 text-sm text-info">
        <Info size={18} className="mt-0.5 shrink-0" />
        <span>
          {heyKiki ? (
            <>
              Deine HeyKiki-Nummer: <span className="font-semibold">{heyKiki}</span> — sie ist unten bereits in die
              Codes eingesetzt.
            </>
          ) : (
            <>
              Deine HeyKiki-Nummer findest du in{' '}
              <Link to="/kiki-zentrale/telefon" className="font-semibold underline hover:opacity-80">
                Kiki-Zentrale → Telefon
              </Link>
              .
            </>
          )}
        </span>
      </div>

      <div className="space-y-4">
        <p className="text-sm text-muted">
          Am einfachsten richten Sie die Rufumleitung direkt in den Einstellungen Ihres Telefons ein
          („Immer weiterleiten"). Klappt das bei deinem Gerät nicht, nutze die Codes weiter unten.
        </p>

        <Card>
          <div className="mb-3 flex items-center gap-2">
            <Smartphone size={16} className="text-muted" />
            <GroupLabel>Schritt für Schritt am iPhone</GroupLabel>
          </div>
          <ol className="space-y-3 text-sm text-body">
            <Step n={1}>Öffne die <span className="font-semibold text-text">Einstellungen</span>.</Step>
            <Step n={2}>Tippe auf <span className="font-semibold text-text">Telefon</span> (bei manchen Tarifen darunter noch <span className="font-semibold text-text">Anrufe</span>).</Step>
            <Step n={3}>Wähle <span className="font-semibold text-text">Rufweiterleitung</span> und aktiviere den Schalter.</Step>
            <Step n={4}>Tippe auf <span className="font-semibold text-text">Weiterleiten an</span> und trage deine HeyKiki-Nummer{numHint} ein.</Step>
          </ol>
        </Card>

        <Card>
          <div className="mb-3 flex items-center gap-2">
            <Smartphone size={16} className="text-muted" />
            <GroupLabel>Schritt für Schritt bei Android</GroupLabel>
          </div>
          <ol className="space-y-3 text-sm text-body">
            <Step n={1}>Öffne die <span className="font-semibold text-text">Telefon-App</span>.</Step>
            <Step n={2}>Tippe oben rechts auf das <span className="font-semibold text-text">Menü (⋮)</span> und dann auf <span className="font-semibold text-text">Einstellungen</span>.</Step>
            <Step n={3}>Wähle <span className="font-semibold text-text">Anrufe</span> bzw. <span className="font-semibold text-text">Anrufkonten</span> und dann <span className="font-semibold text-text">Rufweiterleitung</span>. Bei Samsung: <span className="font-semibold text-text">Einstellungen → Zusätzliche Einstellungen → Rufweiterleitung</span>.</Step>
            <Step n={4}>Wähle <span className="font-semibold text-text">Immer weiterleiten</span> und trage deine HeyKiki-Nummer{numHint} ein.</Step>
          </ol>
          <p className="mt-3 text-xs text-muted">
            Die Bezeichnungen können je nach Hersteller (Samsung, Google, Xiaomi …) leicht abweichen.
          </p>
        </Card>

        <Card>
          <GroupLabel>Falls die Einstellungen keine Rufumleitung anbieten: Codes wählen</GroupLabel>
          <p className="mb-3 text-sm text-muted">
            Diese Tastenkombinationen funktionieren auf den meisten Mobiltelefonen direkt über die Telefon-App —
            eintippen und die Anruf-Taste drücken.{' '}
            {heyKiki
              ? 'Die Codes sind bereits mit deiner HeyKiki-Nummer ausgefüllt.'
              : 'Sobald dir eine HeyKiki-Nummer zugewiesen ist, erscheint sie hier automatisch.'}
          </p>
          <ul className="space-y-2 text-sm text-body">
            <li>
              <span className="font-semibold text-text">Alle Anrufe weiterleiten (empfohlen):</span>{' '}
              <Code>**21*{dial}#</Code>
            </li>
            <li>
              <span className="font-semibold text-text">Status prüfen:</span> <Code>*#21#</Code>
            </li>
            <li>
              <span className="font-semibold text-text">Weiterleitung ausschalten:</span>{' '}
              <Code>##21#</Code> — oder alle Weiterleitungen auf einmal: <Code>##002#</Code>.
            </li>
          </ul>
          <p className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Nur in bestimmten Fällen weiterleiten</p>
          <ul className="space-y-2 text-sm text-body">
            <li>
              <span className="font-semibold text-text">Wenn besetzt:</span> <Code>**67*{dial}#</Code>
            </li>
            <li>
              <span className="font-semibold text-text">Wenn nicht angenommen:</span>{' '}
              <Code>**61*{dial}**20#</Code> <span className="text-muted">(nach 20 Sek.; 5–30 möglich)</span>
            </li>
            <li>
              <span className="font-semibold text-text">Wenn nicht erreichbar:</span> <Code>**62*{dial}#</Code>
            </li>
          </ul>
        </Card>

        <Card>
          <GroupLabel>Mehr Infos beim Anbieter</GroupLabel>
          <p className="mb-3 text-sm text-muted">
            Anleitungen direkt vom Telefonanbieter — je nach Tarif kann die Einrichtung abweichen.
          </p>
          <div className="flex flex-wrap gap-2">
            {PROVIDERS.map((p) => (
              <a
                key={p.label}
                href={p.href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-body hover:bg-alt"
              >
                {p.label}
                <ExternalLink size={13} className="text-muted" />
              </a>
            ))}
          </div>
        </Card>

        <div className="flex items-start gap-3 rounded-xl border border-info/30 bg-info-bg/40 p-4 text-sm text-body">
          <Info size={16} className="mt-0.5 shrink-0 text-info" />
          <span>Eine Rufumleitung innerhalb Deutschlands ist in der Regel kostenlos.</span>
        </div>
      </div>

      <div className="mt-8">
        <Link to="/kiki-zentrale/telefon" className="inline-flex items-center gap-1.5 text-sm font-medium text-green-deep hover:underline">
          <ArrowLeft size={15} /> Zurück zur Kiki-Zentrale
        </Link>
      </div>
    </div>
  )
}
