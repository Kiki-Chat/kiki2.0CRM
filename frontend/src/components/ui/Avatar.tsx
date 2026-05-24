import { initials } from '../../lib/utils'

export function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  return (
    <div
      className="flex flex-shrink-0 items-center justify-center rounded-full bg-green-tint-100 font-bold text-green-deep"
      style={{ width: size, height: size, fontSize: size * 0.38 }}
    >
      {initials(name)}
    </div>
  )
}
