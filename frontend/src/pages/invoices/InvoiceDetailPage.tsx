import { useQuery } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState, NotLiveNotice } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getAuditLog, getInvoice, getInvoiceFileUrl } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import { formatDate, formatPaise, formatQty } from '@/lib/format'
import { cn } from '@/lib/utils'

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
  const invoice = useQuery({ queryKey: ['invoice', invoiceId], queryFn: () => getInvoice(invoiceId), enabled: live, refetchInterval: 5000 })
  const file = useQuery({ queryKey: ['invoice-file', invoiceId], queryFn: () => getInvoiceFileUrl(invoiceId), enabled: live })
  const audit = useQuery({ queryKey: ['audit', invoiceId], queryFn: () => getAuditLog(invoiceId), enabled: live })

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
        title={inv.invoice_no ? `Invoice ${inv.invoice_no}` : `Invoice ${inv.invoice_id}`}
        description={`${inv.supplier_name ?? 'Unknown supplier'} · uploaded ${formatDate(inv.created_at)}`}
        actions={<StatusBadge status={inv.status} />}
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="min-h-[32rem] overflow-hidden py-0">
          {file.data ? (
            <iframe title="Invoice file" src={file.data.url} className="h-full min-h-[32rem] w-full" />
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
              <dl className="grid grid-cols-2 gap-4 text-sm">
                <Field label="Supplier" value={inv.supplier_name} />
                <Field label="Invoice number" value={inv.invoice_no} />
                <Field label="Invoice date" value={inv.invoice_date && formatDate(inv.invoice_date)} />
                <Field label="PO number" value={inv.po_number} />
                <Field label="Total" value={inv.total_paise == null ? null : formatPaise(inv.total_paise)} />
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
                      {a.action}
                      {a.to_status && <span className="font-normal text-muted-foreground"> → {a.to_status.replace(/_/g, ' ')}</span>}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {a.actor} · {new Date(a.timestamp).toLocaleString('en-IN')}
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
