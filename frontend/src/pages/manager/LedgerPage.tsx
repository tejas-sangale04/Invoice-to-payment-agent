import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState, NotLiveNotice } from '@/components/States'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { listLedger } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import { formatDate, formatPaise } from '@/lib/format'

export function LedgerPage() {
  const live = FEATURES.ledger.live
  const ledger = useQuery({ queryKey: ['ledger'], queryFn: listLedger, enabled: live })
  const rows = ledger.data?.items ?? []
  const total = rows.reduce((s, r) => s + r.amount_paise, 0)

  return (
    <>
      <PageHeader title="Ledger" description="Approved invoices posted for payment. Each invoice is posted exactly once." />
      {!live && <NotLiveNotice feature="ledger" />}
      <Card className="py-2">
        <CardContent className="px-2">
          {live && ledger.isPending && <LoadingState />}
          {ledger.isError && <ErrorState error={ledger.error} />}
          {(!live || ledger.isSuccess) && rows.length === 0 && <EmptyState title="Nothing posted yet" />}
          {rows.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Posted</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Invoice</TableHead>
                  <TableHead>PO</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.idempotency_key}>
                    <TableCell>{formatDate(r.posted_at)}</TableCell>
                    <TableCell>{r.supplier_name}</TableCell>
                    <TableCell>
                      <Link to={`/invoices/${r.invoice_id}`} className="underline underline-offset-4">
                        {r.invoice_no}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Link to={`/purchase-orders/${r.po_number}`} className="underline underline-offset-4">
                        {r.po_number}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatPaise(r.amount_paise)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={4}>Total posted</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPaise(total)}</TableCell>
                </TableRow>
              </TableFooter>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  )
}
