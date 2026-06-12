// Smooth drag-and-drop reordering (dnd-kit) — replaces the janky native HTML5
// drag in the Kiki-Zentrale lists. Rows animate out of the way while dragging
// (CSS transforms), and the drag only starts from the grip handle so toggles,
// inputs and buttons inside a row stay fully clickable.
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical } from 'lucide-react'
import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '../../lib/utils'

export function SortableList({
  ids,
  onMove,
  children,
}: {
  ids: string[]
  onMove: (from: number, to: number) => void
  children: ReactNode
}) {
  // distance: 5 → a plain click never registers as a drag.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const handleDragEnd = (e: DragEndEvent) => {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const from = ids.indexOf(String(active.id))
    const to = ids.indexOf(String(over.id))
    if (from !== -1 && to !== -1) onMove(from, to)
  }
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        {children}
      </SortableContext>
    </DndContext>
  )
}

/** One sortable row. `children` is a render-prop receiving the handle props —
 * spread them onto the grip element (and only there). */
export function SortableRow({
  id,
  className,
  children,
}: {
  id: string
  className?: string
  children: (handleProps: HTMLAttributes<HTMLElement>) => ReactNode
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(className, isDragging && 'relative z-10 opacity-90 shadow-e2')}
    >
      {children({ ...(attributes as HTMLAttributes<HTMLElement>), ...(listeners as HTMLAttributes<HTMLElement>) })}
    </div>
  )
}

/** The standard grip — visible affordance that THIS is the drag area. */
export function DragHandle(props: HTMLAttributes<HTMLElement>) {
  return (
    <span
      {...props}
      title="Ziehen zum Sortieren"
      className={cn('cursor-grab touch-none text-faint hover:text-body active:cursor-grabbing', props.className)}
    >
      <GripVertical size={15} />
    </span>
  )
}
