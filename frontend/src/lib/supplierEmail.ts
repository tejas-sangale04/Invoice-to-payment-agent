import { useQuery } from '@tanstack/react-query'

import { getEmailStatus, listSuppliers } from '@/lib/api'
import { splitDraft } from '@/lib/email'
import type { Invoice } from '@/lib/types'

export interface EmailDraft {
  send: boolean
  subject: string
  body: string
}

/** The agent's draft, ready to edit. Sending is on by default when there is a draft. */
export function initialEmail(inv: Invoice): EmailDraft {
  const { subject, body } = splitDraft(inv.supplier_email_draft)
  return { send: Boolean(subject || body), subject, body }
}

export const emailReady = (e: EmailDraft) => e.subject.trim() !== '' && e.body.trim() !== ''

/** Whether email is set up, and where it would go: the supplier on file for this invoice. */
export function useEmailTarget(inv: Invoice) {
  const status = useQuery({ queryKey: ['email-status'], queryFn: getEmailStatus, staleTime: 5 * 60_000 })
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: () => listSuppliers() })
  const supplier = suppliers.data?.items.find((s) => s.supplier_id === inv.match_result?.supplier_id)
  return {
    loading: status.isPending || suppliers.isPending,
    enabled: status.data?.enabled ?? false,
    sender: status.data?.sender ?? null,
    supplier,
    /** Email can go out only when it is set up and the invoice is matched to a supplier. */
    canSend: Boolean(status.data?.enabled && supplier),
  }
}
