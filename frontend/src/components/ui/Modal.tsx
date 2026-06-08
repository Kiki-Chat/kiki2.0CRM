import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

export function Modal({
  open,
  onOpenChange,
  title,
  children,
  footer,
  widthClass = 'max-w-lg',
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: ReactNode
  footer?: ReactNode
  widthClass?: string
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content
          className={`fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[min(92vw,calc(100vw-2rem))] ${widthClass} -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-e3 focus:outline-none`}
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-4 sm:px-6">
            <Dialog.Title className="text-base font-bold text-text sm:text-lg">{title}</Dialog.Title>
            <Dialog.Close className="rounded-md p-1 text-muted hover:bg-alt">
              <X size={18} />
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">{children}</div>
          {footer && (
            <div className="flex-shrink-0 border-t border-border bg-surface px-4 py-4 sm:px-6">{footer}</div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
