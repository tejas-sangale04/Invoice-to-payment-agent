import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '@/components/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { createGoodsReceipt, getPurchaseOrder, listPurchaseOrders } from '@/lib/api'
import { formatQty, remainingQty } from '@/lib/format'

const today = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in local time

export function RecordDeliveryPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const poNumber = params.get('po') ?? ''

  const openPos = useQuery({
    queryKey: ['purchase-orders', 'not-closed'],
    queryFn: async () => (await listPurchaseOrders({ limit: 100 })).items.filter((p) => p.status !== 'closed'),
  })
  const po = useQuery({ queryKey: ['purchase-order', poNumber], queryFn: () => getPurchaseOrder(poNumber), enabled: !!poNumber })

  const [qty, setQty] = useState<Record<string, string>>({})
  const [receivedOn, setReceivedOn] = useState(today)
  const [notes, setNotes] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: createGoodsReceipt,
    onSuccess: (gr) => {
      toast.success(`${gr.gr_id} recorded against ${gr.po_number}`)
      qc.invalidateQueries({ queryKey: ['purchase-order', gr.po_number] })
      qc.invalidateQueries({ queryKey: ['goods-receipts', gr.po_number] })
      navigate(`/purchase-orders/${gr.po_number}`)
    },
  })

  function choosePo(value: string) {
    setQty({})
    setFormError(null)
    setParams(value ? { po: value } : {})
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    const items = Object.entries(qty)
      .filter(([, v]) => v.trim() !== '' && Number(v) !== 0)
      .map(([line_id, v]) => ({ line_id, qty_received: v.trim() }))
    if (items.length === 0) return setFormError('Enter the quantity received for at least one item.')
    if (items.some((i) => !/^\d+(\.\d{1,3})?$/.test(i.qty_received)))
      return setFormError('Quantities must be positive numbers with up to 3 decimals.')
    mutation.mutate({ po_number: poNumber, received_on: receivedOn, notes, items })
  }

  return (
    <>
      <PageHeader title="Record delivery" description="Enter what actually arrived. You can record a partial delivery and the rest later." />
      <form onSubmit={onSubmit}>
        <Card>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="po">Purchase order</Label>
              <NativeSelect id="po" required value={poNumber} onChange={(e) => choosePo(e.target.value)} disabled={openPos.isPending}>
                <option value="">{openPos.isPending ? 'Loading…' : 'Choose an open purchase order'}</option>
                {openPos.data?.map((p) => (
                  <option key={p.po_number} value={p.po_number}>
                    {p.po_number} · {p.supplier_name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="received-on">Received on</Label>
              <Input id="received-on" type="date" required max={today()} value={receivedOn} onChange={(e) => setReceivedOn(e.target.value)} />
            </div>
          </CardContent>

          {!poNumber && openPos.data?.length === 0 && (
            <EmptyState title="No open purchase orders">
              <Link to="/purchase-orders/new" className="underline">
                Create a purchase order
              </Link>{' '}
              first.
            </EmptyState>
          )}
          {poNumber && po.isPending && <LoadingState />}
          {po.isError && (
            <CardContent>
              <ErrorState error={po.error} />
            </CardContent>
          )}
          {po.data && (
            <>
              <CardHeader className="pt-2">
                <CardTitle className="text-base">Items on {po.data.po_number}</CardTitle>
              </CardHeader>
              <CardContent className="px-4">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Item</TableHead>
                      <TableHead className="text-right">Ordered</TableHead>
                      <TableHead className="text-right">Already received</TableHead>
                      <TableHead className="text-right">Still to come</TableHead>
                      <TableHead className="w-36">Received now</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {po.data.items.map((l) => {
                      const left = remainingQty(l.qty, l.qty_received)
                      return (
                        <TableRow key={l.line_id}>
                          <TableCell className="font-medium">{l.name}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatQty(l.qty)} {l.unit}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{formatQty(l.qty_received)}</TableCell>
                          <TableCell className="text-right tabular-nums">{left}</TableCell>
                          <TableCell>
                            <Input
                              aria-label={`Received now: ${l.name}`}
                              inputMode="decimal"
                              placeholder={left === '0' ? 'complete' : '0'}
                              disabled={left === '0'}
                              value={qty[l.line_id] ?? ''}
                              onChange={(e) => setQty((q) => ({ ...q, [l.line_id]: e.target.value }))}
                            />
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </CardContent>
              <CardContent>
                <div className="grid gap-2">
                  <Label htmlFor="notes">Notes (optional)</Label>
                  <Textarea id="notes" placeholder="e.g. 10 L short, driver says rest arrives Friday" value={notes} onChange={(e) => setNotes(e.target.value)} />
                </div>
              </CardContent>
              <CardFooter className="justify-end gap-2 border-t pt-6">
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending ? 'Saving…' : 'Record delivery'}
                </Button>
              </CardFooter>
            </>
          )}
        </Card>
        {(formError || mutation.isError) && (
          <div className="mt-4">
            <ErrorState error={formError ? new Error(formError) : mutation.error!} />
          </div>
        )}
      </form>
    </>
  )
}
