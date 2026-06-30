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

const REVIEWS: Review[] = [
  {
    quote:
      'Was für ein fantastisches Büro-Tool! Wir nutzen Kiki seit etwa drei Monaten, und es macht unsere Arbeit so viel leichter. Man bekommt eine Zusammenfassung, was der Kunde genau wollte und wer er ist – so fällt der Rückruf viel leichter.',
    name: 'Beata Krenzer',
    role: 'Geschäftsführerin, Heizlöwe GmbH',
  },
  {
    quote:
      'Ich bin selbstständiger Malermeister und nutze die KI seit einem Monat – ich bin sehr zufrieden. Auch der Support ist top!',
    name: 'Andy Pasika',
    role: 'Inhaber, Malermeister Andy Pasika',
  },
  {
    quote: 'Kiki ist eine echte Entlastung für uns.',
    name: 'Christian Börenkamp',
    role: 'Geschäftsführer, Tischlerei Börenkamp',
  },
  {
    quote: 'Engagiertes Team. Immer offen für Anregungen und stets bemüht, diese umzusetzen.',
    name: 'Frank Ruschmeier',
    role: 'Geschäftsführer, TrunCAD GmbH',
  },
  {
    quote: 'Support und Technik sind erstklassig!',
    name: 'Tobias Schober',
    role: 'Geschäftsführer, Schober Wohnwerke GmbH',
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
      <div className="relative min-h-[340px]">
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
            <blockquote className="text-2xl font-semibold leading-snug">“{r.quote}”</blockquote>
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
