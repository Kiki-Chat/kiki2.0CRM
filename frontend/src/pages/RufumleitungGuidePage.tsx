import { ArrowLeft, ExternalLink, Info, PhoneForwarded, Smartphone } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Card, GroupLabel } from '../components/kiki/shared'

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
        Damit Kiki Ihre Anrufe entgegennimmt, leiten Sie Ihre bestehende Geschäftsnummer auf Ihre
        HeyKiki-Nummer um. Eingehende Anrufe landen dann automatisch bei Kiki — Ihre gewohnte Nummer
        bleibt unverändert und Sie müssen sie nirgends ändern.
      </p>

      <div className="mb-6 flex gap-3 rounded-lg border border-info/30 bg-info-bg px-4 py-3 text-sm text-info">
        <Info size={18} className="mt-0.5 shrink-0" />
        <span>
          Ihre HeyKiki-Nummer finden Sie in{' '}
          <Link to="/kiki-zentrale/telefon" className="font-semibold underline hover:opacity-80">
            Kiki-Zentrale → Telefon
          </Link>
          .
        </span>
      </div>

      <div className="space-y-4">
        <Card>
          <GroupLabel>Universal-Codes (GSM)</GroupLabel>
          <p className="mb-3 text-sm text-muted">
            Diese Tastenkombinationen funktionieren auf den meisten Mobiltelefonen direkt über die
            Telefon-App. Ersetzen Sie <Code>IHRE-HEYKIKI-NUMMER</Code> durch Ihre HeyKiki-Nummer.
          </p>
          <ul className="space-y-2 text-sm text-body">
            <li>
              <span className="font-semibold text-text">Alle Anrufe umleiten:</span>{' '}
              <Code>*21*IHRE-HEYKIKI-NUMMER#</Code> wählen und die Anruf-Taste drücken.
            </li>
            <li>
              <span className="font-semibold text-text">Umleitung deaktivieren:</span>{' '}
              <Code>#21#</Code> wählen.
            </li>
            <li>
              <span className="font-semibold text-text">Nur bei besetzt:</span>{' '}
              <Code>*67*IHRE-HEYKIKI-NUMMER#</Code>
            </li>
            <li>
              <span className="font-semibold text-text">Nur bei Nichtannahme:</span>{' '}
              <Code>*61*IHRE-HEYKIKI-NUMMER#</Code>
            </li>
          </ul>
        </Card>

        <Card>
          <div className="mb-3 flex items-center gap-2">
            <Smartphone size={16} className="text-muted" />
            <GroupLabel>Schritt für Schritt am iPhone</GroupLabel>
          </div>
          <ol className="space-y-3 text-sm text-body">
            <Step n={1}>Öffnen Sie die <span className="font-semibold text-text">Einstellungen</span>.</Step>
            <Step n={2}>Tippen Sie auf <span className="font-semibold text-text">Telefon</span>.</Step>
            <Step n={3}>Wählen Sie <span className="font-semibold text-text">Rufweiterleitung</span> und aktivieren Sie den Schalter.</Step>
            <Step n={4}>Tippen Sie auf <span className="font-semibold text-text">Weiterleiten an</span> und tragen Sie Ihre HeyKiki-Nummer ein.</Step>
          </ol>
        </Card>

        <Card>
          <div className="mb-3 flex items-center gap-2">
            <Smartphone size={16} className="text-muted" />
            <GroupLabel>Schritt für Schritt bei Android</GroupLabel>
          </div>
          <ol className="space-y-3 text-sm text-body">
            <Step n={1}>Öffnen Sie die <span className="font-semibold text-text">Telefon-App</span>.</Step>
            <Step n={2}>Tippen Sie oben rechts auf das <span className="font-semibold text-text">Menü (⋮)</span> und dann auf <span className="font-semibold text-text">Einstellungen</span>.</Step>
            <Step n={3}>Wählen Sie <span className="font-semibold text-text">Anrufkonten</span> bzw. <span className="font-semibold text-text">Anrufe</span> und dann <span className="font-semibold text-text">Rufweiterleitung</span>.</Step>
            <Step n={4}>Wählen Sie <span className="font-semibold text-text">Immer weiterleiten</span> und tragen Sie Ihre HeyKiki-Nummer ein.</Step>
          </ol>
          <p className="mt-3 text-xs text-muted">
            Die Bezeichnungen können je nach Hersteller (Samsung, Google, Xiaomi …) leicht abweichen.
          </p>
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
