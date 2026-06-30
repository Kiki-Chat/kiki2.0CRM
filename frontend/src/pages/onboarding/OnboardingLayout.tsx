import { useEffect, useState, type ReactNode } from 'react'
import { Star } from 'lucide-react'

import { cn } from '../../lib/utils'

// Authentic Kiki customer reviews (German, for the German funnel). Rotated on the
// right brand panel. Quotes use proper top quotation marks (“ ”), not the German
// low „ marks that read as inverted commas.
interface Review {
  quote: string
  name: string
  role: string
}

// Verbatim customer reviews (their own wording — intentionally not grammar-"corrected").
const REVIEWS: Review[] = [
  {
    quote:
      'Kiki ist für uns eine Erleichterung. Ich kann mich mehr auf die Arbeit konzentrieren, auf der Baustelle und weiß selbst wenn das Telefon klingelt und ich nicht dran gehen kann, Kiki macht das schon!',
    name: 'Christian Börenkamp',
    role: 'Inhaber Tischlerei Börenkamp',
  },
  {
    quote:
      'Ich bin selbständiger Malermeister und nutze die Ki seit 1. Monat bin sehr zufrieden Support ist auch mega!',
    name: 'Andy Pasika',
    role: 'Inhaber von Malermeister Andy Pasika',
  },
  {
    quote:
      'So eine tolle Bürohilfe! Wir nutzen Kiki bereits seit ca. 3 Monaten und es eine große Arbeitserleichterung. Man sieht eine Zusammenfassung was genau der Kunde wollte und um wen es sich handelt. So kann man viel gezielter zurückrufen.',
    name: 'Beata Krenzer',
    role: 'Geschäftsführerin Heizlöwe GmbH',
  },
  {
    quote: 'Support und Technik top!',
    name: 'Tobias Schober',
    role: 'Geschäftsführer Schober Wohnwerke GmbH',
  },
  {
    quote: 'Engagiertes Team. Immer ein offenes Ohr für Vorschläge und immer bemüht diese auch umzusetzen.',
    name: 'Frank Ruschmeier',
    role: 'Geschäftsführer TrunCAD GmbH',
  },
  {
    quote:
      'Seit wir mit Hey Kiki zusammenarbeiten, läuft unsere telefonische Erreichbarkeit reibungslos.\n\nKlare Empfehlung für alle, die sich im Tagesgeschäft entlasten und gleichzeitig professionell erreichbar bleiben möchten!',
    name: 'Norman Hinze',
    role: 'Inhaber Haustechnik Hinze e.K.',
  },
]

function initials(name: string): string {
  return name
    .split(' ')
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase()
}

function ReviewCarousel() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setI((p) => (p + 1) % REVIEWS.length), 6000)
    return () => window.clearInterval(t)
  }, [])

  return (
    <div>
      {/* Crossfade stack — all reviews absolutely positioned; active one fades in. */}
      <div className="relative min-h-[420px]">
        {REVIEWS.map((r, idx) => (
          <div
            key={r.name}
            aria-hidden={idx !== i}
            className={cn(
              'absolute inset-0 transition-opacity duration-700 ease-in-out',
              idx === i ? 'opacity-100' : 'pointer-events-none opacity-0',
            )}
          >
            <div className="mb-4 flex gap-1">
              {Array.from({ length: 5 }).map((_, s) => (
                <Star key={s} size={18} className="text-amber-300" fill="currentColor" strokeWidth={0} />
              ))}
            </div>
            <blockquote className="whitespace-pre-line text-2xl font-semibold leading-snug">“{r.quote}”</blockquote>
            <div className="mt-8 flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/20 text-sm font-bold">
                {initials(r.name)}
              </div>
              <div>
                <div className="font-semibold">{r.name}</div>
                <div className="text-sm text-white/80">{r.role}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Dots */}
      <div className="mt-6 flex gap-2">
        {REVIEWS.map((r, idx) => (
          <button
            key={r.name}
            onClick={() => setI(idx)}
            aria-label={`Bewertung ${idx + 1}`}
            className={cn(
              'h-1.5 rounded-full transition-all',
              idx === i ? 'w-6 bg-white' : 'w-1.5 bg-white/40 hover:bg-white/70',
            )}
          />
        ))}
      </div>
    </div>
  )
}

// fonio-style split: left = the funnel step, right = rotating customer reviews
// (hidden on mobile). Public, no app chrome.
export function OnboardingLayout({
  children,
  step,
}: {
  children: ReactNode
  step?: 1 | 2 | 3
}) {
  return (
    <div className="flex min-h-screen bg-bg">
      {/* Left: content */}
      <div className="flex w-full flex-col px-6 py-8 sm:px-10 lg:w-[52%] lg:px-16">
        <div className="mb-8 flex items-center gap-2">
          <img src="/kiki-logo.jpg" alt="HeyKiki" className="h-9 w-9 rounded-lg object-cover" />
          <span className="text-lg font-bold text-text">HeyKiki</span>
        </div>
        {step && (
          <div className="mb-8 flex items-center gap-2">
            {[1, 2, 3].map((n) => (
              <div
                key={n}
                className={
                  'h-1.5 flex-1 rounded-full ' +
                  (n <= step ? 'bg-green-primary' : 'bg-green-tint-100')
                }
              />
            ))}
          </div>
        )}
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center">{children}</div>
      </div>

      {/* Right: rotating customer reviews */}
      <div className="hidden flex-col justify-between bg-gradient-to-br from-green-primary to-green-deep p-14 text-white lg:flex lg:w-[48%]">
        <div className="pt-6 text-sm font-medium text-white/80">Das sagen unsere Kunden</div>
        <ReviewCarousel />
        <div className="text-sm text-white/70">Die smarte KI-Telefonistin für Handwerksbetriebe</div>
      </div>
    </div>
  )
}
