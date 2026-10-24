import { useQuery } from '@tanstack/react-query'
import { Pencil, Truck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuth } from '@/auth/AuthProvider'
import { getPurchaseOrder, listGoodsReceipts } from '@/lib/api'
import { hasRole } from '@/lib/roles'
import { formatDate, formatPaise, formatQty, remainingQty } from '@/lib/format'

export function PurchaseOrderDetailPage() {
  const { poNumber = '' } = useParams()
  const { role } = useAuth()
  const po = useQuery({ queryKey: ['purchase-order', poNumber], queryFn: () => getPurchaseOrder(poNumber) })
  const receipts = useQuery({ queryKey: ['goods-receipts', poNumber], queryFn: () => listGoodsReceipts(poNumber) })

  if (po.isPending) return <LoadingState />
  if (po.isError) return <ErrorState error={po.error} />
  const data = po.data
  const lineName = Object.fromEntries(data.items.map((l) => [l.line_id, `${l.name} (${l.unit})`]))

  return (
    <>
      <PageHeader
        title={data.po_number}
        description={`${data.supplier_name}${data.po_ref ? ` · invoice reference ${data.po_ref}` : ''} · created ${formatDate(data.created_at)}`}
        actions={
          <div className="flex items-center gap-2">
            {hasRole(role, 'manager') && data.status === 'open' && data.items.every((l) => Number(l.qty_billed) === 0) && (
              <Button variant="outline" asChild>
                <Link to={`/purchase-orders/${data.po_number}/edit`}>
                  <Pencil /> Edit
                </Link>
              </Button>
            )}
            {data.status !== 'closed' && (
              <Button asChild>
                <Link to={`/deliveries/new?po=${data.po_number}`}>
                  <Truck /> Record delivery
                </Link>
              </Button>
            )}
          </div>
        }
      />
      <div className="grid gap-6">
        <Card className="py-2">
          <CardHeader className="flex items-center justify-between pt-4">
            <CardTitle className="text-base">Items</CardTitle>
            <StatusBadge status={data.status} />
          </CardHeader>
          <CardContent className="px-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Ordered</TableHead>
                  <TableHead className="text-right">Received</TableHead>
                  <TableHead className="text-right">Still to come</TableHead>
                  <TableHead className="text-right">Billed</TableHead>
                  <TableHead className="text-right">Unit price</TableHead>
                  <TableHead className="text-right">GST</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((l) => (
                  <TableRow key={l.line_id}>
                    <TableCell>{l.line_id}</TableCell>
                    <TableCell className="font-medium">{l.name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatQty(l.qty)} {l.unit}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatQty(l.qty_received)}</TableCell>
                    <TableCell className="text-right tabular-nums">{remainingQty(l.qty, l.qty_received)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatQty(l.qty_billed)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPaise(l.unit_price_paise)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatQty(l.tax_rate)}%</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPaise(l.line_total_paise + l.tax_paise)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell colSpan={8} className="text-right">
                    Subtotal {formatPaise(data.subtotal_paise)} · GST {formatPaise(data.tax_paise)} · Total
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatPaise(data.total_paise)}</TableCell>
                </TableRow>
              </TableFooter>
            </Table>
          </CardContent>
        </Card>

        <Card className="py-2">
          <CardHeader className="pt-4">
            <CardTitle className="text-base">Deliveries</CardTitle>
          </CardHeader>
          <CardContent className="px-2">
            {receipts.isPending && <LoadingState />}
            {receipts.isError && <ErrorState error={receipts.error} />}
            {receipts.data?.items.length === 0 && <EmptyState title="Nothing received yet" />}
            {!!receipts.data?.items.length && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Receipt</TableHead>
                    <TableHead>Received on</TableHead>
                    <TableHead>Items</TableHead>
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {receipts.data.items.map((gr) => (
                    <TableRow key={gr.gr_id}>
                      <TableCell className="font-medium">{gr.gr_id}</TableCell>
                      <TableCell>{formatDate(gr.received_on)}</TableCell>
                      <TableCell className="whitespace-normal">
                        {gr.items.map((i) => `${formatQty(i.qty_received)} × ${lineName[i.line_id] ?? i.line_id}`).join(', ')}
                      </TableCell>
                      <TableCell className="whitespace-normal text-muted-foreground">{gr.notes || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
