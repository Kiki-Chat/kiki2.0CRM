import * as RadixAccordion from '@radix-ui/react-accordion'
import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

export interface AccordionItem {
  value: string
  title: string
  icon?: ReactNode
  content: ReactNode
}

/**
 * Progressive disclosure default: only the first section is open initially
 * (per the IA spec). Pass `defaultOpenFirst={false}` to start fully collapsed.
 */
export function Accordion({
  items,
  defaultOpenFirst = true,
}: {
  items: AccordionItem[]
  defaultOpenFirst?: boolean
}) {
  return (
    <RadixAccordion.Root
      type="multiple"
      defaultValue={defaultOpenFirst && items[0] ? [items[0].value] : []}
      className="divide-y divide-border"
    >
      {items.map((item) => (
        <RadixAccordion.Item key={item.value} value={item.value}>
          <RadixAccordion.Header>
            <RadixAccordion.Trigger className="group flex w-full items-center gap-2.5 py-3 text-left text-sm font-semibold text-body hover:text-text">
              {item.icon}
              <span className="flex-1">{item.title}</span>
              <ChevronDown
                size={16}
                className="text-muted transition-transform group-data-[state=open]:rotate-180"
              />
            </RadixAccordion.Trigger>
          </RadixAccordion.Header>
          <RadixAccordion.Content className="pb-4">{item.content}</RadixAccordion.Content>
        </RadixAccordion.Item>
      ))}
    </RadixAccordion.Root>
  )
}
