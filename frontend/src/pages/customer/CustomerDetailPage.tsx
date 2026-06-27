import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { CustomerFormModal } from '../../components/CustomerFormModal'
import { apiFetch } from '../../lib/api'
import { fmtTime } from '../../lib/datetime'
import { CustomerDocumentDrawer } from './CustomerDocumentDrawer'
import { CustomerHeader } from './CustomerHeader'
import { CustomerVorgangSection } from './CustomerVorgangSection'
import { GroupingReviewModal } from './GroupingReviewModal'
import { OrphanCallModal } from './OrphanCallModal'
import type { CustomerDetail, DocRow, ModalTarget, PickerState, Proposal } from './types'
import { VorgangAssignPicker } from './VorgangAssignPicker'
import { VorgangDetailModal } from './VorgangDetailModal'

export function CustomerDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editOpen, setEditOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [modal, setModal] = useState<ModalTarget | null>(null)
  const [picker, setPicker] = useState<PickerState | null>(null)
  const [proposal, setProposal] = useState<Proposal | null>(null)

  const { data: customer, isLoading } = useQuery({
    queryKey: ['customerDetail', id],
    queryFn: () => apiFetch<CustomerDetail>(`/api/customers/${id}`),
  })
  const { data: docs = [] } = useQuery({
    queryKey: ['customerDocs', id],
    queryFn: () => apiFetch<DocRow[]>(`/api/customers/${id}/documents`),
  })

  const refresh = () => qc.invalidateQueries({ queryKey: ['customerDetail', id] })

  const propose = useMutation({
    mutationFn: () => apiFetch<Proposal>(`/api/customers/${id}/cases/propose`, { method: 'POST' }),
    onSuccess: (p) => setProposal(p),
  })

  const moveInquiry = useMutation({
    mutationFn: (body: { inquiryId: string; case_id?: string | null; new_case_label?: string }) =>
      apiFetch(`/api/inquiries/${body.inquiryId}/case`, {
        method: 'POST',
        body: JSON.stringify({ case_id: body.case_id, new_case_label: body.new_case_label }),
      }),
    onSuccess: () => {
      setPicker(null)
      setModal(null)
      refresh()
    },
  })

  if (isLoading || !customer) {
    return <div className="flex h-full items-center justify-center text-muted">Wird geladen…</div>
  }

  const cases = customer.cases ?? []
  const modalCase = modal?.kind === 'vorgang' ? cases.find((c) => c.id === modal.id) : null
  const modalInquiry = modal?.kind === 'call' ? (customer.inquiries ?? []).find((i) => i.id === modal.id) : null

  return (
    <div className="mx-auto max-w-[1240px] space-y-5 p-4 md:p-6 lg:p-8">
      <button
        type="button"
        onClick={() => navigate('/customers')}
        className="flex items-center gap-1.5 text-sm text-muted hover:text-body"
      >
        <ArrowLeft size={15} /> Zurück zur Kundenliste
      </button>

      <CustomerHeader
        customer={customer}
        onEdit={() => setEditOpen(true)}
        onCreateOffer={() => navigate(`/cost-estimates/new?customer_id=${customer.id}`)}
        onOpenDocuments={() => setDrawerOpen(true)}
        onKiGrouping={() => propose.mutate()}
        onDelete={() => setEditOpen(true)}
      />

      <CustomerVorgangSection
        customer={customer}
        onOpenModal={setModal}
        onAssignOrphan={(inquiryId) => setPicker({ mode: 'assign', inquiryId })}
      />

      <div className="rounded-lg border border-border bg-surface px-5 py-3 text-xs text-muted">
        Erstellt: {fmtTime(customer.created_at)} · Zuletzt aktualisiert: {fmtTime(customer.updated_at)}
      </div>

      <CustomerDocumentDrawer
        customer={customer}
        docs={docs}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onChange={() => qc.invalidateQueries({ queryKey: ['customerDocs', id] })}
      />

      {modalCase && (
        <VorgangDetailModal
          caseRow={modalCase}
          onClose={() => setModal(null)}
          onTransfer={(inquiryId, fromCaseId) => setPicker({ mode: 'transfer', inquiryId, fromCaseId })}
          onLoosen={(inquiryId) => moveInquiry.mutate({ inquiryId, case_id: null })}
        />
      )}

      {modalInquiry && (
        <OrphanCallModal
          inquiry={modalInquiry}
          onClose={() => setModal(null)}
          onAssign={() => setPicker({ mode: 'assign', inquiryId: modalInquiry.id })}
        />
      )}

      {picker && (
        <VorgangAssignPicker
          mode={picker.mode}
          cases={cases}
          fromCaseId={picker.fromCaseId}
          onClose={() => setPicker(null)}
          onPick={(caseId) => moveInquiry.mutate({ inquiryId: picker.inquiryId, case_id: caseId })}
        />
      )}

      {proposal && (
        <GroupingReviewModal
          customerId={customer.id}
          proposal={proposal}
          onClose={() => setProposal(null)}
          onApplied={() => {
            setProposal(null)
            refresh()
          }}
        />
      )}

      <CustomerFormModal
        open={editOpen}
        mode="edit"
        customer={customer}
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false)
          refresh()
        }}
        onDeleted={() => navigate('/customers')}
      />
    </div>
  )
}
