import type { ReactNode } from 'react'

// fonio-style split: left = the funnel step, right = brand/testimonial panel
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

      {/* Right: brand panel */}
      <div className="hidden flex-col justify-between bg-gradient-to-br from-green-primary to-green-deep p-14 text-white lg:flex lg:w-[48%]">
        <div />
        <div>
          <blockquote className="text-2xl font-semibold leading-snug">
            „Aufgrund der hohen Nachfrage waren unsere Service-Leitungen oft besetzt – und
            Kunden gingen verloren.
            <br />
            <br />
            Kiki nimmt für uns jeden Anruf entgegen – keine verpassten Kunden, kein
            verlorener Umsatz mehr.“
          </blockquote>
          <div className="mt-8 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/20 text-sm font-bold">
              SK
            </div>
            <div>
              <div className="font-semibold">Sasa Krsic</div>
              <div className="text-sm text-white/80">Geschäftsführer &amp; Inhaber Kaffeewelt</div>
            </div>
          </div>
        </div>
        <div className="text-sm text-white/70">Die smarte KI-Telefonistin für Handwerksbetriebe</div>
      </div>
    </div>
  )
}
