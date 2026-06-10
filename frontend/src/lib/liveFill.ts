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
  tool: 'create_invoice' | 'create_cost_estimate'
  args: {
    customer?: string
    customer_id?: string
    subject?: string
    positions?: LiveFillPosition[]
    intro_text?: string
    closing_text?: string
  }
}

const KEY = 'kiki-live-fill'
export const LIVE_FILL_EVENT = 'kiki-live-fill-status'

export interface LiveFillStatus {
  tool: LiveFillPayload['tool']
  status: 'done' | 'failed'
  note?: string
  route?: string
}

export function requestLiveFill(payload: LiveFillPayload): void {
  sessionStorage.setItem(KEY, JSON.stringify(payload))
}

/** One-shot read for the target form page; clears the request so a reload of
 * the form never re-runs the script. */
export function consumeLiveFill(tool: LiveFillPayload['tool']): LiveFillPayload | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const p = JSON.parse(raw) as LiveFillPayload
    if (p?.tool !== tool) return null
    sessionStorage.removeItem(KEY)
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
