import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Copy, RotateCcw } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState, NotLiveNotice } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/auth/AuthProvider'
import { getAuditLog, getInvoice, getInvoiceFileUrl, reprocessInvoice } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import { formatDate, formatPaise, formatQty } from '@/lib/format'
import { hasRole } from '@/lib/roles'
import type { InvoiceStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

// While the agent is working the page polls; once it settles, it stops.
const PROCESSING: InvoiceStatus[] = ['received', 'extracting', 'extracted', 'validated', 'matched']
const REPROCESSABLE: InvoiceStatus[] = ['on_hold', 'needs_review', 'failed']
const ATTENTION: InvoiceStatus[] = ['on_hold', 'needs_review', 'failed', 'blocked_duplicate', 'rejected']

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value || '—'}</dd>
    </div>
  )
}

export function InvoiceDetailPage() {
  const { invoiceId = '' } = useParams()
  const live = FEATURES.invoices.live
  const { user, role } = useAuth()
  const qc = useQueryClient()
  const invoice = useQuery({
    queryKey: ['invoice', invoiceId],
    queryFn: () => getInvoice(invoiceId),
    enabled: live,
    refetchInterval: (q) => (q.state.data && PROCESSING.includes(q.state.data.status) ? 2000 : false),
  })
  // Signed links last 15 minutes; fetch a fresh one well before that.
  const file = useQuery({ queryKey: ['invoice-file', invoiceId], queryFn: () => getInvoiceFileUrl(invoiceId), enabled: live, staleTime: 10 * 60_000, refetchInterval: 10 * 60_000 })
  const audit = useQuery({ queryKey: ['audit', invoiceId, invoice.data?.updated_at], queryFn: () => getAuditLog(invoiceId), enabled: live && !!invoice.data })
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
  const match = inv.match_result

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
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Extracted details</CardTitle>
            </CardHeader>
            <CardContent>
              {!inv.extracted && <p className="mb-4 text-sm text-muted-foreground">Not read yet.</p>}
              <dl className="grid grid-cols-2 gap-4 text-sm">
                <Field label="File" value={`${inv.file_name} (${Math.ceil(inv.file_size / 1024)} KB)`} />
                <Field label="Supplier" value={inv.extracted?.supplier_name} />
                <Field label="Invoice number" value={inv.extracted?.invoice_no} />
                <Field label="Invoice date" value={inv.extracted?.invoice_date && formatDate(inv.extracted?.invoice_date)} />
                <Field label="PO number" value={inv.extracted?.po_number} />
                <Field label="Total" value={inv.extracted?.total_paise == null ? null : formatPaise(inv.extracted?.total_paise)} />
              </dl>
            </CardContent>
          </Card>

          <Card className="py-2">
            <CardHeader className="pt-4">
              <CardTitle className="text-base">3-way match {match?.matched_po && `against ${match.matched_po}`}</CardTitle>
            </CardHeader>
            <CardContent className="px-2">
              {!match ? (
                <EmptyState title="Not matched yet" />
              ) : (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Item</TableHead>
                        <TableHead className="text-right">Billed</TableHead>
                        <TableHead className="text-right">Received, unbilled</TableHead>
                        <TableHead className="text-right">Billed price</TableHead>
                        <TableHead className="text-right">PO price</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {match.per_line.map((l, i) => (
                        <TableRow key={i} className={cn(l.issue && 'bg-warning/10')}>
                          <TableCell className="font-medium">
                            {l.name}
                            {l.issue && <p className="text-xs font-normal text-amber-700">{l.issue}</p>}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{formatQty(l.billed_qty)}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatQty(l.available_qty)}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatPaise(l.billed_unit_price_paise)}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatPaise(l.po_unit_price_paise)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <dl className="grid grid-cols-2 gap-4 p-2 text-sm">
                    <Field label="Correct amount" value={formatPaise(match.correct_amount_paise)} />
                    <Field label="Difference" value={formatPaise(match.difference_paise)} />
                  </dl>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex items-center justify-between">
              <CardTitle className="text-base">Decision</CardTitle>
              {inv.decision && <StatusBadge status={inv.decision} />}
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              {inv.decision_reason && <p className="font-medium">{inv.decision_reason}</p>}
              {inv.explanation && <p className="text-muted-foreground">{inv.explanation}</p>}
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
            </CardContent>
          </Card>

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
