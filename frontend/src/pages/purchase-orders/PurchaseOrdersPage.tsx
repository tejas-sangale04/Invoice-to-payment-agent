import { useInfiniteQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { listPurchaseOrders } from '@/lib/api'
import { formatDate, formatPaise } from '@/lib/format'
import type { POStatus } from '@/lib/types'

const STATUSES: POStatus[] = ['open', 'partially_billed', 'fully_billed', 'closed']

export function PurchaseOrdersPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const status = (params.get('status') as POStatus | null) ?? undefined

  const pos = useInfiniteQuery({
    queryKey: ['purchase-orders', status],
    queryFn: ({ pageParam }) => listPurchaseOrders({ status, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
  const rows = pos.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description="What you ordered, and how much of it has arrived."
        actions={
          <Button asChild>
            <Link to="/purchase-orders/new">
              <Plus /> New purchase order
            </Link>
          </Button>
        }
      />
      <div className="mb-4 w-full sm:w-56">
        <NativeSelect
          aria-label="Filter by status"
          value={status ?? ''}
          onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {})}
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </NativeSelect>
      </div>
      <Card className="py-2">
        <CardContent className="px-2">
          {pos.isPending && <LoadingState />}
          {pos.isError && <ErrorState error={pos.error} />}
          {pos.isSuccess && rows.length === 0 && (
            <EmptyState title="No purchase orders">
              <Link to="/purchase-orders/new" className="underline">
                Create the first one
              </Link>
            </EmptyState>
          )}
          {rows.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>PO</TableHead>
                  <TableHead>Supplier</TableHead>
                  <TableHead>Lines</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((po) => (
                  <TableRow key={po.po_number} className="cursor-pointer" onClick={() => navigate(`/purchase-orders/${po.po_number}`)}>
                    <TableCell className="font-medium">
                      <Link to={`/purchase-orders/${po.po_number}`} onClick={(e) => e.stopPropagation()}>
                        {po.po_number}
                      </Link>
                      {po.po_ref && <span className="ml-2 text-xs font-normal text-muted-foreground">{po.po_ref}</span>}
                    </TableCell>
                    <TableCell>{po.supplier_name}</TableCell>
                    <TableCell>{po.items.length}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPaise(po.total_paise)}</TableCell>
                    <TableCell>
                      <StatusBadge status={po.status} />
                    </TableCell>
                    <TableCell>{formatDate(po.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {pos.hasNextPage && (
            <div className="flex justify-center p-2">
              <Button variant="outline" size="sm" onClick={() => pos.fetchNextPage()} disabled={pos.isFetchingNextPage}>
                {pos.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}
