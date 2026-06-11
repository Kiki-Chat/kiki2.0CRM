// Hey-Kiki "live fill" protocol — the browser-takeover effect for form-backed
// writes. Instead of silently POSTing a confirmed copilot action, the panel
// stores the payload here, navigates to the real form (/invoices/new), and the
// form page animates filling its own fields (customer → subject typed
// character-by-character → positions appearing one by one) before saving.
// Cooperative rather than DOM-puppeteering: identical look, none of the
// brittleness of synthesizing events against React-controlled inputs.

export interface LiveFillPosition {
  description?: string
  quantity?: number
  unit?: string
  price?: number
  vat?: number
}

export interface LiveFillPayload {
  tool: 'create_invoice' | 'create_cost_estimate' | 'create_appointment'
  // Stamped by requestLiveFill — consumeLiveFill discards stale payloads so a
  // leftover request can never auto-create a duplicate document on a LATER
  // visit to the form (audit 2026-06-11).
  ts?: number
  args: {
    customer?: string
    customer_id?: string
    subject?: string
    positions?: LiveFillPosition[]
    intro_text?: string
    closing_text?: string
    // create_appointment
    title?: string
    scheduled_at?: string
    duration_minutes?: number
    location?: string
    assigned_employee_id?: string
    notes?: string
  }
}

const KEY = 'kiki-live-fill'
export const LIVE_FILL_EVENT = 'kiki-live-fill-status'
// Fired when a request is stored, so a target page that is ALREADY mounted
// (navigate() to the same route does not remount) can pick it up too.
export const LIVE_FILL_REQUEST_EVENT = 'kiki-live-fill-request'

export interface LiveFillStatus {
  tool: LiveFillPayload['tool']
  // 'started' = the form began the takeover script — the panel cancels its
  // fallback timer so the two paths can never BOTH execute the write.
  status: 'started' | 'done' | 'failed'
  note?: string
  route?: string
}

// A payload older than this is stale — the panel's fallback already executed
// (or the user navigated away); consuming it would duplicate the document.
const MAX_AGE_MS = 2 * 60 * 1000

export function requestLiveFill(payload: LiveFillPayload): void {
  sessionStorage.setItem(KEY, JSON.stringify({ ...payload, ts: Date.now() }))
  window.dispatchEvent(
    new CustomEvent(LIVE_FILL_REQUEST_EVENT, { detail: { tool: payload.tool } }),
  )
}

/** Drop a pending request — called by the panel when its fallback executes the
 * write directly, so a later-mounting form can't run the script a second time. */
export function clearLiveFill(): void {
  sessionStorage.removeItem(KEY)
}

/** One-shot read for the target form page; clears the request so a reload of
 * the form never re-runs the script. Stale payloads are discarded. */
export function consumeLiveFill(tool: LiveFillPayload['tool']): LiveFillPayload | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const p = JSON.parse(raw) as LiveFillPayload
    if (p?.tool !== tool) return null
    sessionStorage.removeItem(KEY)
    if (p.ts && Date.now() - p.ts > MAX_AGE_MS) return null
    return p
  } catch {
    sessionStorage.removeItem(KEY)
    return null
  }
}

export function emitLiveFillStatus(detail: LiveFillStatus): void {
  window.dispatchEvent(new CustomEvent<LiveFillStatus>(LIVE_FILL_EVENT, { detail }))
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
