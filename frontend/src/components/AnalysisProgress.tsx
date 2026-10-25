import { Check, Loader2 } from 'lucide-react'

import type { InvoiceStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

const STEPS = [
  { title: 'Reading', hint: 'Pulling out the supplier, items and totals' },
  { title: 'Checking', hint: 'Validating the numbers and the supplier' },
  { title: 'Matching', hint: 'Comparing with the purchase order and deliveries' },
  { title: 'Deciding', hint: 'Choosing approve, hold or send to a manager' },
  { title: 'Posting', hint: 'Recording the invoice against the PO' },
]

const ACTIVE: Partial<Record<InvoiceStatus, number>> = {
  received: 0,
  extracting: 0,
  extracted: 1,
  validated: 2,
  matched: 3,
  auto_approved: 4,
  approved: 4,
}

/** Shows where the agent is while it works on an invoice. */
export function AnalysisProgress({ status }: { status: InvoiceStatus }) {
  const active = ACTIVE[status] ?? 0
  return (
    <div role="status" aria-live="polite" className="rounded-xl border bg-card p-5">
      <p className="text-sm font-medium">The agent is working on this invoice</p>
      <p className="mb-4 text-sm text-muted-foreground">{STEPS[active].hint}. This page updates by itself.</p>
      <ol className="grid gap-3 sm:grid-cols-5">
        {STEPS.map((step, i) => {
          const done = i < active
          const current = i === active
          return (
            <li key={step.title} className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-1.5">
              <div className="flex items-center gap-2 sm:w-full">
                <span
                  className={cn(
                    'flex size-6 shrink-0 items-center justify-center rounded-full border text-xs',
                    done && 'border-brand bg-brand text-primary-foreground',
                    current && 'border-brand bg-brand-soft text-brand',
                    !done && !current && 'text-muted-foreground',
                  )}
                >
                  {done ? <Check className="size-3.5" /> : current ? <Loader2 className="size-3.5 animate-spin" /> : i + 1}
                </span>
                <span className={cn('hidden h-px flex-1 sm:block', done ? 'bg-brand' : 'bg-border', i === STEPS.length - 1 && 'sm:invisible')} />
              </div>
              <span className={cn('text-sm', current ? 'font-medium' : 'text-muted-foreground')}>{step.title}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
