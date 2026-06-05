// Center + right orchestrator. Owns the detail queries/mutations/modals/timeline
// (identical wiring to the original CallDetail) and composes Transcript + Workspace.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../../lib/api'
import { AppointmentCard, usePendingAppointment, type PendingAppointment } from './AppointmentCard'
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
}: {
  callId: string
  isSuperAdmin: boolean
  emergency: boolean
  rightOpen: boolean
  onToggleRight: () => void
  onDeleted?: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'actions' | 'details' | 'course'>('actions')
  const [modal, setModal] = useState<'process' | 'appointment' | null>(null)

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

  const pendingAppt = usePendingAppointment(callId)
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
    return <div className="flex flex-1 items-center justify-center text-muted">Lädt…</div>
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
            <Workspace
              call={call}
              inquiry={inquiry}
              employees={employees}
              busy={patchInquiry.isPending || deleteCall.isPending}
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
            />
          </aside>
        </>
      )}

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
        }}
      />
    </>
  )
}
