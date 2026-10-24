import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Copy, RotateCcw, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { SupplierEmailEditor } from '@/components/SupplierEmailEditor'
import { ErrorState, LoadingState, NotLiveNotice } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuth } from '@/auth/AuthProvider'
import { ExtractedCard } from '@/pages/invoices/ExtractedCard'
import { MatchCard } from '@/pages/invoices/MatchCard'
import { deleteInvoice, emailSupplier, getAuditLog, getInvoice, getInvoiceFileUrl, reprocessInvoice } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import { emailReady, initialEmail, useEmailTarget } from '@/lib/supplierEmail'
import { formatDate } from '@/lib/format'
import { hasRole } from '@/lib/roles'
import type { Invoice, InvoiceStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

// While the agent is working the page polls; once it settles, it stops.
const PROCESSING: InvoiceStatus[] = ['received', 'extracting', 'extracted', 'validated', 'matched', 'auto_approved', 'approved']
const REPROCESSABLE: InvoiceStatus[] = ['on_hold', 'needs_review', 'failed']
const DELETABLE: InvoiceStatus[] = ['needs_review', 'failed', 'on_hold', 'pending_approval', 'rejected', 'blocked_duplicate']
const EMAILABLE: InvoiceStatus[] = ['pending_approval', 'rejected', 'on_hold', 'needs_review', 'blocked_duplicate']
const ATTENTION: InvoiceStatus[] = ['on_hold', 'needs_review', 'failed', 'blocked_duplicate', 'rejected']

function EmailSupplierCard({ inv }: { inv: Invoice }) {
  const qc = useQueryClient()
  const target = useEmailTarget(inv)
  const [email, setEmail] = useState(() => initialEmail(inv))
  const last = inv.supplier_email
  const send = useMutation({
    mutationFn: () => emailSupplier(inv.invoice_id, { subject: email.subject.trim(), body: email.body.trim() }),
    onSuccess: (data) => {
      qc.setQueryData(['invoice', inv.invoice_id], data)
      qc.invalidateQueries({ queryKey: ['audit', inv.invoice_id] })
      if (data.supplier_email?.status === 'sent') toast.success(`Emailed ${data.supplier_email.to}`)
      else toast.error(`The email could not be sent: ${data.supplier_email?.error}`)
    },
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Email the supplier</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        {last && (
          <p className={last.status === 'sent' ? 'text-green-700' : 'text-destructive'}>
            {last.status === 'sent'
              ? `Emailed ${last.to} on ${new Date(last.at).toLocaleString('en-IN')} (${last.by_email ?? last.by}): ${last.subject}`
              : `The last email to ${last.to} could not be sent: ${last.error}`}
          </p>
        )}
        <SupplierEmailEditor inv={inv} value={email} onChange={setEmail} toggle={false} />
        {send.isError && <ErrorState error={send.error} />}
      </CardContent>
      {target.canSend && (
        <div className="flex justify-end px-6 pb-6">
          <Button disabled={!emailReady(email) || send.isPending} onClick={() => send.mutate()}>
            <Send /> {last?.status === 'sent' ? 'Send again' : 'Send email'}
          </Button>
        </div>
      )}
    </Card>
  )
}

export function InvoiceDetailPage() {
  const { invoiceId = '' } = useParams()
  const live = FEATURES.invoices.live
  const { user, role } = useAuth()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const invoice = useQuery({
    queryKey: ['invoice', invoiceId],
    queryFn: () => getInvoice(invoiceId),
    enabled: live,
    refetchInterval: (q) => (q.state.data && PROCESSING.includes(q.state.data.status) ? 2000 : false),
  })
  // Signed links last 15 minutes; fetch a fresh one well before that.
  const file = useQuery({ queryKey: ['invoice-file', invoiceId], queryFn: () => getInvoiceFileUrl(invoiceId), enabled: live, staleTime: 10 * 60_000, refetchInterval: 10 * 60_000 })
  const audit = useQuery({ queryKey: ['audit', invoiceId, invoice.data?.updated_at], queryFn: () => getAuditLog(invoiceId), enabled: live && !!invoice.data })
  const remove = useMutation({
    mutationFn: () => deleteInvoice(invoiceId),
    onSuccess: () => {
      toast.success('Invoice deleted')
      qc.removeQueries({ queryKey: ['invoice', invoiceId] })
      qc.invalidateQueries({ queryKey: ['invoices'] })
      navigate('/invoices')
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not delete the invoice'),
  })
  const reprocess = useMutation({
    mutationFn: () => reprocessInvoice(invoiceId),
    onSuccess: (data) => {
      toast.success('Sent back through the pipeline')
      qc.setQueryData(['invoice', invoiceId], data)
      qc.invalidateQueries({ queryKey: ['invoices'] })
    },
  })

  if (!live)
    return (
      <>
        <PageHeader title={`Invoice ${invoiceId}`} />
        <NotLiveNotice feature="invoices" />
      </>
    )
  if (invoice.isPending) return <LoadingState />
  if (invoice.isError) return <ErrorState error={invoice.error} />
  const inv = invoice.data

  return (
    <>
      <PageHeader
        title={inv.extracted?.invoice_no ? `Invoice ${inv.extracted.invoice_no}` : inv.invoice_id}
        description={`${inv.extracted?.supplier_name ?? inv.file_name} · uploaded ${formatDate(inv.created_at)}`}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge status={inv.status} />
            {hasRole(role, 'manager') && REPROCESSABLE.includes(inv.status) && (
              <Button size="sm" variant="outline" disabled={reprocess.isPending} onClick={() => reprocess.mutate()}>
                <RotateCcw /> Reprocess
              </Button>
            )}
            {hasRole(role, 'manager') && DELETABLE.includes(inv.status) && (
              <Button
                size="sm"
                variant="outline"
                disabled={remove.isPending}
                onClick={() => {
                  if (window.confirm('Delete this invoice? Its audit history is kept. You can then upload a corrected copy.')) remove.mutate()
                }}
              >
                <Trash2 /> Delete
              </Button>
            )}
          </div>
        }
      />
      {inv.status_reason && (
        <div
          className={cn(
            'mb-6 flex items-start gap-3 rounded-md border p-4 text-sm',
            ATTENTION.includes(inv.status) ? 'border-warning/40 bg-warning/10' : 'bg-background',
          )}
        >
          {ATTENTION.includes(inv.status) && <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700" />}
          <p>{inv.status_reason}</p>
        </div>
      )}
      {PROCESSING.includes(inv.status) && (
        <div className="mb-6">
          <LoadingState label="The agent is working on this invoice…" />
        </div>
      )}
      {reprocess.isError && (
        <div className="mb-6">
          <ErrorState error={reprocess.error} />
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="min-h-[32rem] overflow-hidden py-0">
          {file.data ? (
            file.data.content_type.startsWith('image/') ? (
              <img src={file.data.url} alt={`Invoice ${inv.file_name}`} className="w-full object-contain" />
            ) : (
              <iframe title="Invoice file" src={file.data.url} className="h-full min-h-[32rem] w-full" />
            )
          ) : file.isError ? (
            <CardContent className="py-6">
              <ErrorState error={file.error} />
            </CardContent>
          ) : (
            <LoadingState label="Loading file…" />
          )}
        </Card>

        <div className="grid content-start gap-6">
          <ExtractedCard inv={inv} />

          <MatchCard inv={inv} />

          <Card>
            <CardHeader className="flex items-center justify-between">
              <CardTitle className="text-base">Decision</CardTitle>
              {inv.decision && <StatusBadge status={inv.decision} />}
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              {inv.decision_reason && <p className="font-medium">{inv.decision_reason}</p>}
              {inv.explanation && (
                <div className="grid gap-1">
                  <p className="text-muted-foreground">{inv.explanation}</p>
                  <p className="text-xs text-muted-foreground">
                    {inv.explanation_source === 'agent'
                      ? 'Written by the agent from the match results; the amounts were checked.'
                      : 'Standard wording from the match results.'}
                  </p>
                </div>
              )}
              {inv.supplier_email_draft && (
                <div className="rounded-md border bg-muted/40 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">Draft email to supplier</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigator.clipboard.writeText(inv.supplier_email_draft!).then(() => toast.success('Copied'))}
                    >
                      <Copy /> Copy
                    </Button>
                  </div>
                  <p className="whitespace-pre-wrap">{inv.supplier_email_draft}</p>
                </div>
              )}
              {!inv.decision && <p className="text-muted-foreground">The agent hasn't decided yet.</p>}
              {inv.approved_by && (
                <p>
                  Approved by {inv.approved_by === user?.uid ? 'you' : (inv.approved_by_email ?? inv.approved_by)}
                  {inv.approval_comment && `: ${inv.approval_comment}`}
                </p>
              )}
              {inv.rejected_by && (
                <p>
                  Rejected by {inv.rejected_by === user?.uid ? 'you' : (inv.rejected_by_email ?? inv.rejected_by)}:{' '}
                  {inv.rejection_reason}
                </p>
              )}
              {inv.status === 'pending_approval' && hasRole(role, 'manager') && (
                <p>
                  <Link to="/approvals" className="underline underline-offset-4">
                    Approve or reject it in the approval queue
                  </Link>
                </p>
              )}
              {inv.ledger_key && (
                <p className="text-green-700">
                  Posted to the{' '}
                  <Link to="/ledger" className="underline underline-offset-4">
                    ledger
                  </Link>{' '}
                  for payment.
                </p>
              )}
            </CardContent>
          </Card>

          {hasRole(role, 'manager') && EMAILABLE.includes(inv.status) && (inv.supplier_email_draft || inv.supplier_email) && (
            <EmailSupplierCard key={inv.supplier_email?.at ?? 'draft'} inv={inv} />
          )}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Audit trail</CardTitle>
            </CardHeader>
            <CardContent>
              {audit.isPending && <LoadingState />}
              {audit.isError && <ErrorState error={audit.error} />}
              <ol className="grid gap-3 border-l pl-4 text-sm">
                {audit.data?.items.map((a, i) => (
                  <li key={i}>
                    <p className="font-medium">
                      {a.action.charAt(0).toUpperCase() + a.action.slice(1).replace(/_/g, " ")}
                      {a.to_status && <span className="font-normal text-muted-foreground"> → {a.to_status.replace(/_/g, ' ')}</span>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {a.actor === user?.uid ? 'You' : a.actor === 'agent' ? 'Agent' : a.actor} · {new Date(a.timestamp).toLocaleString('en-IN')}
                    </p>
                    {a.details && <p className="text-muted-foreground">{a.details}</p>}
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}
