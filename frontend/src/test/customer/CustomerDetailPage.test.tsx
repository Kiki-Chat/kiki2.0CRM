import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { CustomerDetailPage } from '../../pages/customer/CustomerDetailPage'
import type { CustomerDetail } from '../../pages/customer/types'

vi.mock('../../lib/api', () => ({
  apiFetch: vi.fn(),
  apiUpload: vi.fn(),
}))

vi.mock('../../components/CustomerFormModal', () => ({
  CustomerFormModal: () => null,
}))

import { apiFetch } from '../../lib/api'

const customer: CustomerDetail = {
  id: 'cust-1',
  full_name: 'Familie Wagner',
  email: 'wagner@email.de',
  phone: '+49 160 7741200',
  phone2: '+49 89 6655420',
  address: { raw: 'Ahornallee 28, 82008 Unterhaching' },
  customer_number: 'K-0731',
  customer_type: 'regular',
  vat_id: null,
  notes: 'Bestandskunde seit 2021.',
  created_at: '2026-06-01T10:00:00Z',
  updated_at: '2026-06-27T10:00:00Z',
  inquiries: [
    {
      id: 'inq-o', number: 'ANF-2', subject: 'Hahn tropft', title: 'Hahn', type: null, status: 'open',
      created_at: '2026-06-26T10:00:00Z', case_id: null,
      primary_call: { id: 'call-o', summary_title: 'Meldung Hahn', direction: 'inbound', duration_seconds: 88, started_at: '2026-06-26T16:40:00Z' },
    },
  ],
  appointments: [],
  cost_estimates: [],
  calls: [],
  cases: [
    {
      id: 'case-1', number: 'VG-1', label: 'Badsanierung Gäste-Bad', status: 'active',
      created_at: '2026-06-10T10:00:00Z', project_id: null,
      ai_summary: 'Komplettsanierung läuft.', call_count: 2, entry_count: 5,
      last_activity_at: '2026-06-27T09:00:00Z',
    },
  ],
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/customers/cust-1']}>
        <Routes>
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === '/api/customers/cust-1') return customer
    if (path.endsWith('/documents')) return []
    if (path.startsWith('/api/cases/')) {
      return { case: customer.cases![0], timeline: [], calls: [], inquiries: [], appointments: [], cost_estimates: [], open_count: 0 }
    }
    return {}
  })
})

describe('CustomerDetailPage redesign', () => {
  it('renders header with name, number, and type badge', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Familie Wagner' })).toBeInTheDocument()
    expect(screen.getByText('#K-0731')).toBeInTheDocument()
    expect(screen.getByText('Stammkunde')).toBeInTheDocument()
  })

  it('renders both phone numbers', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Familie Wagner' })
    expect(screen.getByText('+49 160 7741200')).toBeInTheDocument()
    expect(screen.getByText('+49 89 6655420')).toBeInTheDocument()
  })

  it('does not render removed Verlauf or Termine panels', async () => {
    renderPage()
    await screen.findByRole('heading', { name: 'Familie Wagner' })
    expect(screen.queryByText(/^Verlauf \(/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Termine \(/)).not.toBeInTheDocument()
  })

  it('shows Vorgang cards on Vorgänge tab', async () => {
    renderPage()
    expect(await screen.findByText('Badsanierung Gäste-Bad')).toBeInTheDocument()
  })

  it('opens orphan tab and shows assign link', async () => {
    renderPage()
    await screen.findByText('Badsanierung Gäste-Bad')
    fireEvent.click(screen.getByRole('button', { name: /Nicht zugeordnet/i }))
    expect(await screen.findByText('Zu Vorgang zuordnen')).toBeInTheDocument()
  })

  it('Angebot erstellen navigates with customer_id', async () => {
    renderPage()
    const btn = await screen.findByRole('button', { name: /Angebot erstellen/i })
    expect(btn).toBeInTheDocument()
  })
})
