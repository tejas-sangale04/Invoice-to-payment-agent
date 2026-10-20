import { useInfiniteQuery } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState, NotLiveNotice } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { listInvoices } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import { formatDate, formatPaise } from '@/lib/format'
import type { InvoiceStatus } from '@/lib/types'

const STATUSES: InvoiceStatus[] = [
  'received', 'extracting', 'matched', 'auto_approved', 'pending_approval', 'approved',
  'rejected', 'posted', 'paid', 'on_hold', 'blocked_duplicate', 'needs_review', 'failed',
]

export function InvoicesPage() {
  const live = FEATURES.invoices.live
  const navigate = useNavigate()
  const [status, setStatus] = useState<InvoiceStatus | ''>('')
  const [supplier, setSupplier] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  const invoices = useInfiniteQuery({
    queryKey: ['invoices', status],
    queryFn: ({ pageParam }) => listInvoices({ status: status || undefined, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: live,
    refetchInterval: 5000, // statuses change while the agent works
  })

  // Supplier and date filters run on the loaded rows.
  const rows = (invoices.data?.pages.flatMap((p) => p.items) ?? []).filter(
    (inv) =>
      (!supplier || (inv.supplier_name ?? '').toLowerCase().includes(supplier.toLowerCase())) &&
      (!from || (inv.invoice_date ?? inv.created_at) >= from) &&
      (!to || (inv.invoice_date ?? inv.created_at).slice(0, 10) <= to),
  )

  return (
    <>
      <PageHeader
        title="Invoices"
        description="Every uploaded invoice and where it is in the process. Refreshes automatically."
        actions={
          <Button asChild>
            <Link to="/invoices/upload">
              <Upload /> Upload invoice
            </Link>
          </Button>
        }
      />
      {!live && <NotLiveNotice feature="invoices" />}
      <div className="mb-4 grid gap-2 sm:grid-cols-4">
        <NativeSelect aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as InvoiceStatus | '')}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </NativeSelect>
        <Input aria-label="Supplier" placeholder="Supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
        <Input aria-label="From date" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input aria-label="To date" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>
      <Card className="py-2">
        <CardContent className="px-2">
          {!live && <EmptyState title="No invoices yet" />}
          {live && invoices.isPending && <LoadingState />}
          {invoices.isError && <ErrorState error={invoices.error} />}
          {invoices.isSuccess && rows.length === 0 && <EmptyState title="No invoices match these filters" />}
          {rows.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>PO</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Uploaded</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((inv) => (
                  <TableRow key={inv.invoice_id} className="cursor-pointer" onClick={() => navigate(`/invoices/${inv.invoice_id}`)}>
                    <TableCell className="font-medium">{inv.invoice_no ?? inv.invoice_id}</TableCell>
                    <TableCell>{inv.supplier_name ?? '—'}</TableCell>
                    <TableCell>{inv.po_number ?? '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{inv.total_paise == null ? '—' : formatPaise(inv.total_paise)}</TableCell>
                    <TableCell>
                      <StatusBadge status={inv.status} />
                    </TableCell>
                    <TableCell>{formatDate(inv.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {invoices.hasNextPage && (
            <div className="flex justify-center p-2">
              <Button variant="outline" size="sm" onClick={() => invoices.fetchNextPage()}>
                Load more
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}
