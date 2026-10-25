import { cn } from '@/lib/utils'

/** The InvoiceFlow logo: an invoice sheet with a check mark. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand text-primary-foreground', className)} aria-hidden>
      <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 3h9l4 4v14H6z" />
        <path d="M9 14l2 2 4-4" />
      </svg>
    </span>
  )
}
