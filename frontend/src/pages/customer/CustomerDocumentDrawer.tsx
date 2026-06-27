import { Download, FileText, Image as ImageIcon, Upload, X } from 'lucide-react'
import { useRef, useState } from 'react'

import { Tag } from '../../components/ui/Tag'
import { apiUpload } from '../../lib/api'
import { fmtDate } from '../../lib/datetime'
import { cn } from '../../lib/utils'
import type { CustomerDetail, DocRow } from './types'

interface Props {
  customer: CustomerDetail
  docs: DocRow[]
  open: boolean
  onClose: () => void
  onChange: () => void
}

export function CustomerDocumentDrawer({ customer, docs, open, onClose, onChange }: Props) {
  const [tab, setTab] = useState<'photos' | 'documents'>('documents')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const photos = docs.filter((d) => d.is_image)
  const documents = docs.filter((d) => !d.is_image)

  if (!open) return null

  async function upload(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    try {
      for (const f of Array.from(files)) {
        const fd = new FormData()
        fd.append('file', f)
        fd.append('category', tab === 'photos' ? 'Foto' : 'Dokument')
        await apiUpload(`/api/customers/${customer.id}/documents`, fd)
      }
      onChange()
    } finally {
      setUploading(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/30" onClick={onClose} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-border bg-surface shadow-e3">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <div className="text-base font-bold text-text">Dokumente &amp; Fotos</div>
            <div className="text-xs text-muted">{customer.full_name ?? 'Kunde'}</div>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-alt">
            <X size={20} />
          </button>
        </div>
        <div className="flex gap-4 border-b border-border px-5 pt-3">
          <button
            type="button"
            onClick={() => setTab('photos')}
            className={cn('flex items-center gap-1.5 border-b-2 pb-2 text-sm font-medium', tab === 'photos' ? 'border-green-primary text-green-deep' : 'border-transparent text-muted')}
          >
            <ImageIcon size={15} /> Fotos ({photos.length})
          </button>
          <button
            type="button"
            onClick={() => setTab('documents')}
            className={cn('flex items-center gap-1.5 border-b-2 pb-2 text-sm font-medium', tab === 'documents' ? 'border-green-primary text-green-deep' : 'border-transparent text-muted')}
          >
            <FileText size={15} /> Dokumente ({documents.length})
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          <div
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              upload(e.dataTransfer.files)
            }}
            className="mb-4 cursor-pointer rounded-xl border-2 border-dashed border-border p-8 text-center hover:bg-alt"
          >
            <Upload size={28} className="mx-auto mb-2 text-faint" />
            <div className="text-sm text-body">{uploading ? 'Lädt hoch…' : 'Datei hierher ziehen oder klicken'}</div>
            <div className="text-xs text-faint">JPG, PNG, PDF · max. 10 MB</div>
            <input ref={fileRef} type="file" multiple accept="image/*,application/pdf" className="hidden" onChange={(e) => upload(e.target.files)} />
          </div>
          {tab === 'photos' ? (
            photos.length ? (
              <div className="grid grid-cols-2 gap-3">
                {photos.map((p) => (
                  <a key={p.id} href={p.url ?? '#'} target="_blank" rel="noreferrer" className="block">
                    <img src={p.url ?? ''} alt={p.name ?? ''} className="aspect-square w-full rounded-lg border border-border object-cover" />
                  </a>
                ))}
              </div>
            ) : (
              <p className="py-6 text-center text-sm text-muted">Noch keine Fotos.</p>
            )
          ) : documents.length ? (
            <div className="space-y-2">
              {documents.map((d) => (
                <div key={d.id} className="flex items-center gap-3 rounded-lg border border-border p-3">
                  <FileText size={16} className="text-warning" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-text">{d.name}</div>
                    <div className="text-xs text-muted">{fmtDate(d.uploaded_at)}</div>
                  </div>
                  {d.category && <Tag variant="info">{d.category}</Tag>}
                  {d.url && (
                    <a href={d.url} target="_blank" rel="noreferrer" className="rounded-md p-1.5 text-muted hover:bg-alt">
                      <Download size={15} />
                    </a>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-muted">Noch keine Dokumente.</p>
          )}
        </div>
      </aside>
    </>
  )
}
