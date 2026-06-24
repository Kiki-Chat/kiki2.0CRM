// Center + right orchestrator. Owns the detail queries/mutations/modals/timeline
// (identical wiring to the original CallDetail) and composes Transcript + Workspace.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ListChecks, MessageSquare } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../../lib/api'
import { AppointmentCard, usePendingAppointment, type PendingAppointment } from './AppointmentCard'
import { Segmented } from './atoms'
import { CreateAppointmentModal, ProcessRequestModal } from './Modals'
import { ResizeHandle, useColumnResize } from './resize'
import { Transcript } from './Transcript'
import { Workspace } from './Workspace'
import type { CallDetailData, CallListItem, Employee, Inquiry, TimelineEvent } from './shared'

export function CallDetail({
  callId,
  isSuperAdmin,
  emergency,
  rightOpen,
  onToggleRight,
  onDeleted,
  isWide = true,
  onBack,
}: {
  callId: string
  isSuperAdmin: boolean
  emergency: boolean
  rightOpen: boolean
  onToggleRight: () => void
  onDeleted?: () => void
  isWide?: boolean
  onBack?: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'actions' | 'details' | 'course'>('actions')
  const [modal, setModal] = useState<'process' | 'appointment' | null>(null)
  // Mobile single-pane: which of transcript / workspace is showing.
  const [mobileView, setMobileView] = useState<'transcript' | 'workspace'>('transcript')

  const { data: call } = useQuery({
    queryKey: ['call', callId],
    queryFn: () => apiFetch<CallDetailData>(`/api/calls/${callId}`),
  })
  const { data: inquiry } = useQuery({
    queryKey: ['callInquiry', callId],
    queryFn: () => apiFetch<Inquiry>(`/api/calls/${callId}/inquiry`, { method: 'POST' }),
  })
  const { data: employees = [] } = useQuery({
    queryKey: ['employees'],
    queryFn: () => apiFetch<Employee[]>('/api/employees'),
  })

  // Sibling cases for the "Anderem Vorgang zuordnen" triage control — other
  // inquiries for the same customer, read from the already-cached call list.
  const { data: callsList } = useQuery({
    queryKey: ['calls'],
    queryFn: () => apiFetch<{ calls: CallListItem[] }>('/api/calls?limit=100'),
  })

  const patchInquiry = useMutation({
    mutationFn: (body: Partial<Inquiry>) =>
      apiFetch<Inquiry>(`/api/inquiries/${inquiry!.id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['callInquiry', callId] })
      qc.invalidateQueries({ queryKey: ['calls'] })
      qc.invalidateQueries({ queryKey: ['dashboard', 'overview'] })
    },
  })

  // Delete the whole call (soft-delete on the server). Clears the selection via
  // onDeleted so the cockpit lands on the next call instead of a stale pane.
  const deleteCall = useMutation({
    mutationFn: () => apiFetch(`/api/calls/${callId}`, { method: 'DELETE' }),
    // Optimistic: drop the row from the list cache immediately so it vanishes with
    // zero lag, and the parent's auto-select lands on the correct next call instead
    // of re-picking this (still-cached) one — the "stuck on the transcript" bug.
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ['calls'] })
      const prev = qc.getQueryData<{ calls: CallListItem[] }>(['calls'])
      qc.setQueryData<{ calls: CallListItem[] }>(['calls'], (old) =>
        old ? { ...old, calls: old.calls.filter((c) => c.id !== callId) } : old,
      )
      onDeleted?.()
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(['calls'], ctx.prev) // restore the row on failure
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['calls'] })
      qc.invalidateQueries({ queryKey: ['dashboard', 'overview'] })
    },
  })

  // ── Cockpit triage (moved here from the Posteingang inbox) ────────────────
  // Move this call into a different existing Vorgang/Fall.
  const moveInquiry = useMutation({
    mutationFn: (inquiryId: string) =>
      apiFetch(`/api/calls/${callId}/assign-inquiry`, {
        method: 'POST',
        body: JSON.stringify({ inquiry_id: inquiryId }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['callInquiry', callId] })
      qc.invalidateQueries({ queryKey: ['call', callId] })
      qc.invalidateQueries({ queryKey: ['calls'] })
      qc.invalidateQueries({ queryKey: ['pe'] }) // keep the Posteingang in sync
    },
  })

  // Mark a junk call as spam (reversible server-side). Optimistically drops it
  // from the list and clears the selection, mirroring delete.
  const setSpam = useMutation({
    mutationFn: () =>
      apiFetch(`/api/calls/${callId}/spam`, { method: 'POST', body: JSON.stringify({ spam: true }) }),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ['calls'] })
      const prev = qc.getQueryData<{ calls: CallListItem[] }>(['calls'])
      qc.setQueryData<{ calls: CallListItem[] }>(['calls'], (old) =>
        old ? { ...old, calls: old.calls.filter((c) => c.id !== callId) } : old,
      )
      onDeleted?.()
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['calls'], ctx.prev)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['calls'] })
      qc.invalidateQueries({ queryKey: ['pe'] }) // keep the Posteingang in sync
    },
  })

  const moveCandidates = useMemo(() => {
    const custId = call?.customer_id ?? null
    const seen = new Set<string>()
    const out: { inquiryId: string; label: string; ticket: string | null }[] = []
    for (const cc of callsList?.calls ?? []) {
      if (!cc.inquiry_id || cc.inquiry_id === inquiry?.id) continue
      // Same customer only (null === null buckets unknown-caller calls together),
      // so a call can't be filed into an unrelated customer's case.
      if (cc.customer_id !== custId) continue
      if (seen.has(cc.inquiry_id)) continue
      seen.add(cc.inquiry_id)
      out.push({
        inquiryId: cc.inquiry_id,
        label: cc.case_label || cc.inquiry_subject || cc.summary_title || 'Vorgang',
        ticket: cc.case_number || cc.inquiry_number,
      })
    }
    return out
  }, [callsList, inquiry?.id, call?.customer_id])

  const pendingAppt = usePendingAppointment(callId)

  // Techniker-Einsatz lebt am bestätigten Termin (Kalender → Termin-Details →
  // „Techniker einsetzen“) — bewusst NICHT mehr am Anrufprotokoll.
  const [dismissedApptIds, setDismissedApptIds] = useState<Set<string>>(new Set())
  // After Bestätigen/Ablehnen the appointment leaves the "pending" set and the
  // server stops returning it — but we keep the card on screen (as a reminder /
  // proof the action happened) from this local snapshot until the user removes
  // it with ✕. Reschedule already persists server-side as "Alternative gesendet".
  const [actioned, setActioned] = useState<{ appt: PendingAppointment; result: 'confirmed' | 'rejected' } | null>(null)
  const livePending = pendingAppt.data?.appointment ?? null
  const shownAppt = livePending ?? actioned?.appt ?? null
  const shownResult = actioned && shownAppt?.id === actioned.appt.id ? actioned.result : undefined
  const showAppointmentCard = !!shownAppt && !dismissedApptIds.has(shownAppt.id)

  // Timeline is lazy — only fetched when the Verlauf tab is open (as before).
  const timeline = useQuery({
    queryKey: ['callTimeline', callId],
    queryFn: () => apiFetch<TimelineEvent[]>(`/api/calls/${callId}/timeline`),
    enabled: !!call && tab === 'course',
  })

  const rightResize = useColumnResize('hk-calls-right-w', 360, { min: 300, max: 600, side: 'right' })

  if (!call) {
    return <div className="flex flex-1 items-center justify-center text-muted">Wird geladen…</div>
  }

  const appointmentSlot =
    showAppointmentCard && shownAppt ? (
      <AppointmentCard
        appointment={shownAppt}
        callId={callId}
        result={shownResult}
        onConfirmed={() => setActioned({ appt: shownAppt, result: 'confirmed' })}
        onRejected={() => setActioned({ appt: shownAppt, result: 'rejected' })}
        onRemove={() => setDismissedApptIds((prev) => new Set(prev).add(shownAppt.id))}
      />
    ) : null

  const workspaceNode = (
    <Workspace
      call={call}
      inquiry={inquiry}
      employees={employees}
      busy={patchInquiry.isPending || deleteCall.isPending || setSpam.isPending || moveInquiry.isPending}
      emergency={emergency}
      tab={tab}
      setTab={setTab}
      timeline={timeline.data ?? []}
      timelineLoading={timeline.isLoading}
      appointmentSlot={appointmentSlot}
      onStatus={(s) => patchInquiry.mutate({ status: s })}
      onDelete={() => {
        if (
          window.confirm(
            'Diesen Anruf wirklich löschen? Die zugehörige Anfrage wird ebenfalls entfernt.',
          )
        )
          deleteCall.mutate()
      }}
      onAssign={(id) => patchInquiry.mutate({ assigned_employee_id: id })}
      onEdit={() => setModal('process')}
      onAppointment={() => setModal('appointment')}
      onKva={
        call.customer_id
          ? () =>
              navigate(
                `/cost-estimates/new?customer_id=${call.customer_id}` +
                  (inquiry?.id ? `&inquiry_id=${inquiry.id}` : ''),
              )
          : undefined
      }
      onOpenCustomer={() => call.customer_id && navigate(`/customers/${call.customer_id}`)}
      candidates={moveCandidates}
      onMoveToInquiry={(iid) => moveInquiry.mutate(iid)}
      onSpam={() => {
        if (window.confirm('Diesen Anruf als Spam markieren? Er wird aus der Liste entfernt (reversibel).'))
          setSpam.mutate()
      }}
    />
  )

  const modals = (
    <>
      {inquiry && (
        <ProcessRequestModal
          open={modal === 'process'}
          onClose={() => setModal(null)}
          inquiry={inquiry}
          onSave={(body) => {
            patchInquiry.mutate(body)
            setModal(null)
          }}
        />
      )}
      <CreateAppointmentModal
        open={modal === 'appointment'}
        onClose={() => setModal(null)}
        call={call}
        inquiryId={inquiry?.id}
        employees={employees}
        onCreated={() => {
          setModal(null)
          qc.invalidateQueries({ queryKey: ['callInquiry', callId] })
          // Reflect the new appointment on the calendar + the call's action card
          // right away (was missing → calendar only updated after a manual reload).
          qc.invalidateQueries({ queryKey: ['appointments'] })
          qc.invalidateQueries({ queryKey: ['pendingAppointment', callId] })
          qc.invalidateQueries({ queryKey: ['actions', 'pending'] })
        }}
      />
    </>
  )

  // ── Mobile (< lg): single pane — back button + Transkript/Bearbeiten toggle.
  // The 3-pane desktop cockpit can't fit, so we show one pane at a time.
  if (!isWide) {
    return (
      <div className="flex h-full min-h-0 w-full flex-col bg-surface">
        <div className="flex items-center gap-2 border-b border-border bg-surface px-3 py-2">
          <button
            onClick={onBack}
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-bold text-body hover:bg-alt"
          >
            <ChevronLeft size={15} /> Liste
          </button>
          <div className="ml-auto">
            <Segmented
              value={mobileView}
              onChange={(v) => setMobileView(v as 'transcript' | 'workspace')}
              options={[
                { value: 'transcript', label: 'Transkript', icon: MessageSquare },
                { value: 'workspace', label: 'Bearbeiten', icon: ListChecks },
              ]}
            />
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col">
          {mobileView === 'transcript' ? (
            <Transcript
              call={call}
              isSuperAdmin={isSuperAdmin}
              onOpenSummary={() => {
                setTab('details')
                setMobileView('workspace')
              }}
            />
          ) : (
            workspaceNode
          )}
        </div>
        {modals}
      </div>
    )
  }

  // ── Desktop (≥ lg): the resizable transcript + optional workspace cockpit.
  return (
    <>
      <Transcript
        call={call}
        isSuperAdmin={isSuperAdmin}
        onOpenSummary={() => setTab('details')}
        onToggleRight={onToggleRight}
        rightOpen={rightOpen}
      />

      {rightOpen && (
        <>
          <ResizeHandle onMouseDown={rightResize.onMouseDown} />
          <aside
            style={{ width: rightResize.width }}
            className="flex h-full flex-shrink-0 flex-col border-l border-border bg-surface"
          >
            {workspaceNode}
          </aside>
        </>
      )}

      {modals}
    </>
  )
}
