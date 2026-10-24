import { useMutation } from '@tanstack/react-query'
import { Mail, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { draftSupplierEmail } from '@/lib/api'
import { splitDraft } from '@/lib/email'
import { type EmailDraft, emailReady, useEmailTarget } from '@/lib/supplierEmail'
import type { Invoice } from '@/lib/types'

interface Props {
  inv: Invoice
  value: EmailDraft
  onChange: (value: EmailDraft) => void
  /** Show the "email the supplier" tick box (off where the whole form is about sending). */
  toggle?: boolean
  verb?: string
  /** Word the agent's email as a rejection notice. */
  rejected?: boolean
}

export function SupplierEmailEditor({ inv, value, onChange, toggle = true, verb = 'this rejection', rejected = false }: Props) {
  const target = useEmailTarget(inv)
  // The manager reads the agent's email before it goes, so it starts open.
  const [expanded, setExpanded] = useState(true)
  const write = useMutation({
    mutationFn: () => draftSupplierEmail(inv.invoice_id, rejected),
    onSuccess: (res) => {
      const { subject, body } = splitDraft(res.email)
      onChange({ send: true, subject, body })
      setExpanded(true)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not write the email'),
  })
  if (target.loading) return null

  if (!target.enabled)
    return (
      <p className="text-xs text-muted-foreground">
        Emails to suppliers aren't set up yet. Add the mail settings to <code>backend/.env</code> (see <code>.env.example</code>) to send
        them from here.
      </p>
    )
  if (!target.supplier)
    return (
      <p className="text-xs text-muted-foreground">
        This invoice isn't matched to a supplier on file, so there is no address to email. Add the supplier first, or write to them
        yourself.
      </p>
    )

  const open = !toggle || value.send
  // Nothing to send yet (no draft): go straight to writing it.
  const showFields = expanded || !emailReady(value)
  return (
    <div className="grid gap-2 rounded-md border bg-muted/30 p-3 text-sm">
      {toggle ? (
        <label className="flex items-center gap-2 font-medium">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={value.send}
            onChange={(e) => onChange({ ...value, send: e.target.checked })}
          />
          <Mail className="size-4" /> Email {target.supplier.name} about {verb}
        </label>
      ) : (
        <p className="flex items-center gap-2 font-medium">
          <Mail className="size-4" /> Email {target.supplier.name}
        </p>
      )}
      {open && (
        <p className="text-xs text-muted-foreground">
          To {target.supplier.email}
          {target.sender && <> · from {target.sender}</>}
          {value.subject && !showFields && <> · “{value.subject}”</>}.{' '}
          {emailReady(value) && (
            <button type="button" className="underline underline-offset-4" onClick={() => setExpanded(!expanded)}>
              {expanded ? 'Hide' : 'Review or edit'}
            </button>
          )}
        </p>
      )}
      {open && (
        <Button type="button" variant="outline" size="sm" className="w-fit" disabled={write.isPending} onClick={() => write.mutate()}>
          <Sparkles /> {write.isPending ? 'Writing…' : emailReady(value) ? 'Write it again' : 'Write it for me'}
        </Button>
      )}
      {open && showFields && (
        <>
          <Input aria-label="Email subject" placeholder="Subject" value={value.subject} onChange={(e) => onChange({ ...value, subject: e.target.value })} />
          <Textarea
            aria-label="Email message"
            className="min-h-40"
            placeholder="Message"
            value={value.body}
            onChange={(e) => onChange({ ...value, body: e.target.value })}
          />
        </>
      )}
    </div>
  )
}
