// Admin-surface HTTP helpers. Bound to the **admin** Supabase client
// (storageKey `heykiki-admin-auth`) so the Bearer token attached to every
// request comes from the admin session — independent of any customer session
// the same browser might also hold.
//
// Every file under frontend/src/admin/ must import from here, NOT from
// `lib/api` (which is the customer-bound bundle).
import { _admin } from './api'

export const apiFetch = _admin.apiFetch
export const apiBlobUrl = _admin.apiBlobUrl
export const apiPostBlob = _admin.apiPostBlob
export const apiUpload = _admin.apiUpload
export const authToken = _admin.authToken
