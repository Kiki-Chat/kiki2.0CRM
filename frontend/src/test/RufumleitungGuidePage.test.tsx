import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { RufumleitungGuidePage } from '../pages/RufumleitungGuidePage'

// RufumleitungGuidePage uses <Link> and useNavigate, so it must render inside a
// router — MemoryRouter is the lightweight wrapper for tests.
function renderPage() {
  return render(
    <MemoryRouter>
      <RufumleitungGuidePage />
    </MemoryRouter>,
  )
}

describe('RufumleitungGuidePage', () => {
  it('renders the page heading', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Rufumleitung einrichten' })).toBeInTheDocument()
  })

  it('shows the universal GSM forwarding code (*21*)', () => {
    renderPage()
    // The code is rendered inside a <code> element: *21*IHRE-HEYKIKI-NUMMER#
    expect(screen.getByText(/\*21\*IHRE-HEYKIKI-NUMMER#/)).toBeInTheDocument()
    // …and the deactivation code #21#
    expect(screen.getByText('#21#')).toBeInTheDocument()
  })

  it('shows the conditional GSM codes for busy / no-answer', () => {
    renderPage()
    expect(screen.getByText(/\*67\*IHRE-HEYKIKI-NUMMER#/)).toBeInTheDocument()
    expect(screen.getByText(/\*61\*IHRE-HEYKIKI-NUMMER#/)).toBeInTheDocument()
  })

  it('links to the three German telco providers with correct hrefs', () => {
    renderPage()
    const telekom = screen.getByRole('link', { name: /Telekom/ })
    const vodafone = screen.getByRole('link', { name: /Vodafone/ })
    const o2 = screen.getByRole('link', { name: /O2/ })

    expect(telekom).toHaveAttribute('href', expect.stringContaining('telekom.de'))
    expect(vodafone).toHaveAttribute('href', expect.stringContaining('vodafone.de'))
    expect(o2).toHaveAttribute('href', expect.stringContaining('o2business.de'))

    // External provider links open in a new tab safely.
    expect(telekom).toHaveAttribute('target', '_blank')
    expect(telekom).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('links back to the Kiki-Zentrale phone settings', () => {
    renderPage()
    const backLinks = screen.getAllByRole('link', { name: /Kiki-Zentrale/ })
    expect(backLinks.length).toBeGreaterThan(0)
  })
})
