import { Badge } from '@/components/ui/badge'
import type { Decision, InvoiceStatus, POStatus } from '@/lib/types'

type Tone = 'success' | 'warning' | 'destructive' | 'secondary'

// Green = OK, amber = needs attention, red = problem. Everything else is neutral.
const TONES: Record<string, Tone> = {
  // invoice status
  auto_approved: 'success',
  approved: 'success',
  posted: 'success',
  paid: 'success',
  pending_approval: 'warning',
  on_hold: 'warning',
  needs_review: 'warning',
  rejected: 'destructive',
  blocked_duplicate: 'destructive',
  failed: 'destructive',
  // decisions
  auto_approve: 'success',
  manager_approval: 'warning',
  hold: 'warning',
  block: 'destructive',
  // PO status
  fully_billed: 'success',
}

export function StatusBadge({ status }: { status: InvoiceStatus | Decision | POStatus }) {
  return <Badge variant={TONES[status] ?? 'secondary'}>{status.replace(/_/g, ' ')}</Badge>
}
