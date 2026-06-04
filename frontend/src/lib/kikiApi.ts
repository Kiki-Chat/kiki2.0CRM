// Types + constants for the Kiki-Zentrale module.

export const KZ = '/api/kiki-zentrale'
export const KZ_STALE = 5 * 60 * 1000

export interface KzConfig {
  kiki_level: number // legacy (dormant) — replaced by the per-capability fields below
  appointments_enabled: boolean
  appointments_level: number
  kva_enabled: boolean
  kva_level: number
  projects_enabled: boolean
  projects_level: number
  invoices_enabled: boolean
  invoices_level: number
  welcome_message: string | null
  trade: string | null
  knowledge_text: string
  forwarding_number: string | null
  incoming_forwarding_number: string | null
  scheduling_enabled: boolean
  buffer_minutes: number
  max_appointments_per_day: number
  parallel_slots: number
  lead_time_days: number
  lead_time_only_weekdays: boolean
  lead_time_earliest_clock: string | null
  price_info_enabled: boolean
  kva_automation_enabled: boolean
  problem_description: string | null
  emergency_enabled: boolean
  emergency_number: string | null
  emergency_only_outside_business_hours: boolean
  emergency_keywords: string[]
  emergency_extra_windows: { from?: string; to?: string; label?: string; weekdays?: string[] }[]
  emergency_surcharge_notice_enabled: boolean
  emergency_surcharge_text: string | null
  outbound_enabled: boolean
  outbound_occasions: Record<string, boolean>
  outbound_time_from: string
  outbound_time_to: string
  outbound_weekdays: string[]
  // 17 — appointment outbound sub-options
  outbound_appt_confirm_enabled: boolean
  outbound_appt_cancel_enabled: boolean
  outbound_appt_reschedule_enabled: boolean
  // 18 — outbound retry
  outbound_retry_max_attempts: number
  outbound_retry_interval_minutes: number
  outbound_recall_on_short_hangup: boolean
  outbound_short_hangup_seconds: number
  // 20 — time-based welcome variants
  welcome_messages: { from?: string; to?: string; message?: string }[]
}

export interface KzAgentState {
  reachable: boolean
  persona_name?: string | null
  first_message?: string | null
  language?: string | null
  voice_id?: string | null
  audio_event_present?: boolean
  tools_count?: number
  knowledge_count?: number
  prompt_length?: number
  error?: string
}

export interface KzSnapshot {
  id: string
  endpoint_label: string
  created_at: string
}

export interface KzOverview {
  config: KzConfig
  phone_number: string | null
  existing_business_number: string | null
  ai_minutes_quota: number | null
  agent: KzAgentState
  recent_snapshots: KzSnapshot[]
}

export interface KzHealth {
  reachable: boolean
  audio_event_present: boolean
  prompt_non_empty: boolean
  first_message_non_empty: boolean
  voice_set: boolean
  language: string | null
  last_check_at: string
  error?: string
}

export interface KzRequiredField {
  id: string
  field_key: string
  label: string
  description: string | null
  is_locked: boolean
  is_duty: boolean
  identification_role: string | null
  sort_order: number
}

export interface KzCategory {
  id: string
  name: string
  description: string | null
  duration_minutes: number
  default_employee_id: string | null
  sort_order: number
}

export interface KzService {
  id: string
  name: string
  is_offered: boolean
}

export interface KzResource {
  id: string
  kind: 'url' | 'pdf'
  source: string
  display_name: string
  chunk_count: number
  status: 'pending' | 'processing' | 'ready' | 'error'
  status_message: string | null
  elevenlabs_doc_id: string | null
  created_at: string
}

export interface KzVoice {
  voice_id: string
  name: string
  preview_url: string | null
  labels: Record<string, string>
  languages: string[]
}

export interface KzPromptHistory {
  snapshot_id: string
  created_at: string
  actor_id: string | null
  prompt: string
}

export interface KzAudit {
  id: string
  endpoint_label: string
  actor_id: string | null
  actor_name: string | null
  agent_id: string
  snapshot_id: string | null
  fields_changed: Record<string, { old: unknown; new: unknown }>
  elevenlabs_response_status: number | null
  elevenlabs_response_excerpt: string | null
  rolled_back: boolean
  rolled_back_at: string | null
  created_at: string
}

// Maps a sub-nav section slug → the endpoint_label used by the safety layer,
// so the per-section rollback strip can find the latest snapshot.
export const SECTION_ENDPOINT_LABEL: Record<string, string> = {
  verhalten: 'verhalten',
  'prompt-editor': 'prompt-editor',
  'branche-kontext': 'knowledge_resource_push',
}

export function minutesAgo(iso: string): number {
  return Math.round((Date.now() - new Date(iso).getTime()) / 60000)
}
