import { Construction } from 'lucide-react'

export function Placeholder({ title }: { title: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-muted">
      <Construction size={32} className="text-faint" />
      <div className="text-lg font-semibold text-text">{title}</div>
      <p className="text-sm">Dieser Bereich folgt in einer späteren Version.</p>
    </div>
  )
}
