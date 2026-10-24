import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { ErrorState, LoadingState } from '@/components/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { createPurchaseOrder, getPurchaseOrder, type POItemInput, listSuppliers, updatePurchaseOrder } from '@/lib/api'
import { formatPaise, lineAmounts, rupeesToPaise } from '@/lib/format'
import type { PurchaseOrder } from '@/lib/types'

const GST_RATES = ['0', '5', '12', '18', '28']

interface Line {
  key: number
  name: string
  qty: string
  unit: string
  price: string // rupees, as typed
  tax_rate: string
}

let nextKey = 1
const blankLine = (): Line => ({ key: nextKey++, name: '', qty: '', unit: '', price: '', tax_rate: '0' })

/** New PO, or (at /purchase-orders/:poNumber/edit) the lines of an existing one. */
export function CreatePurchaseOrderPage() {
  const { poNumber } = useParams()
  const existing = useQuery({ queryKey: ['purchase-order', poNumber], queryFn: () => getPurchaseOrder(poNumber!), enabled: !!poNumber })
  if (poNumber && existing.isPending) return <LoadingState />
  if (poNumber && existing.isError) return <ErrorState error={existing.error} />
  return <PurchaseOrderForm po={existing.data} />
}

function PurchaseOrderForm({ po }: { po?: PurchaseOrder }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: () => listSuppliers() })
  const [supplierId, setSupplierId] = useState(po?.supplier_id ?? '')
  const [lines, setLines] = useState<Line[]>(() =>
    po
      ? po.items.map((l) => ({ key: nextKey++, name: l.name, qty: l.qty, unit: l.unit, price: (l.unit_price_paise / 100).toFixed(2), tax_rate: String(Number(l.tax_rate)) }))
      : [blankLine()],
  )
  const [formError, setFormError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: { supplier_id: string; items: POItemInput[] }) =>
      po ? updatePurchaseOrder(po.po_number, body.items) : createPurchaseOrder(body),
    onSuccess: (saved) => {
      toast.success(`${saved.po_number} ${po ? 'updated' : 'created'}`)
      qc.invalidateQueries({ queryKey: ['purchase-orders'] })
      qc.invalidateQueries({ queryKey: ['purchase-order', saved.po_number] })
      navigate(`/purchase-orders/${saved.po_number}`)
    },
  })

  const update = (key: number, patch: Partial<Line>) =>
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))

  const computed = lines.map((l) => {
    const paise = rupeesToPaise(l.price)
    return paise === null ? null : lineAmounts(l.qty, paise, l.tax_rate)
  })
  const subtotal = computed.reduce((s, c) => s + (c?.total ?? 0), 0)
  const tax = computed.reduce((s, c) => s + (c?.tax ?? 0), 0)

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    const items = []
    for (const [i, l] of lines.entries()) {
      const price = rupeesToPaise(l.price)
      if (price === null) return setFormError(`Line ${i + 1}: enter the unit price in rupees, e.g. 60 or 60.50`)
      if (!computed[i] || Number(l.qty) <= 0) return setFormError(`Line ${i + 1}: enter a quantity above 0 (up to 3 decimals)`)
      items.push({ name: l.name, qty: l.qty.trim(), unit: l.unit, unit_price_paise: price, tax_rate: l.tax_rate })
    }
    mutation.mutate({ supplier_id: supplierId, items })
  }

  return (
    <>
      <PageHeader
        title={po ? `Edit ${po.po_number}` : 'New purchase order'}
        description={po ? 'Change what is ordered. Not possible once an invoice has been posted against it.' : "Record what you're ordering and at what price."}
      />
      <form onSubmit={onSubmit}>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Supplier</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid max-w-md gap-2">
              <Label htmlFor="supplier">Supplier</Label>
              <NativeSelect id="supplier" required value={supplierId} onChange={(e) => setSupplierId(e.target.value)} disabled={suppliers.isPending || !!po}>
                <option value="">{suppliers.isPending ? 'Loading suppliers…' : 'Choose a supplier'}</option>
                {suppliers.data?.items.map((s) => (
                  <option key={s.supplier_id} value={s.supplier_id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
              {suppliers.data?.items.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No suppliers yet. An admin can add one on the <Link to="/suppliers" className="underline">Suppliers</Link> page.
                </p>
              )}
            </div>
          </CardContent>

          <CardHeader className="pt-2">
            <CardTitle className="text-base">Items</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            <div className="hidden grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr_auto] gap-2 text-xs font-medium text-muted-foreground lg:grid">
              <span>Item</span>
              <span>Quantity</span>
              <span>Unit</span>
              <span>Unit price (₹)</span>
              <span>GST %</span>
              <span className="text-right">Line total</span>
              <span className="w-9" />
            </div>
            {lines.map((l, i) => (
              <div key={l.key} className="grid grid-cols-2 gap-2 rounded-md border p-3 lg:grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr_auto] lg:items-center lg:border-0 lg:p-0">
                <Input aria-label={`Item ${i + 1} name`} placeholder="Milk" required className="col-span-2 lg:col-span-1" value={l.name} onChange={(e) => update(l.key, { name: e.target.value })} />
                <Input aria-label={`Item ${i + 1} quantity`} placeholder="50" inputMode="decimal" required value={l.qty} onChange={(e) => update(l.key, { qty: e.target.value })} />
                <Input aria-label={`Item ${i + 1} unit`} placeholder="L" required maxLength={20} value={l.unit} onChange={(e) => update(l.key, { unit: e.target.value })} />
                <Input aria-label={`Item ${i + 1} unit price`} placeholder="60.00" inputMode="decimal" required value={l.price} onChange={(e) => update(l.key, { price: e.target.value })} />
                <NativeSelect aria-label={`Item ${i + 1} GST rate`} value={l.tax_rate} onChange={(e) => update(l.key, { tax_rate: e.target.value })}>
                  {GST_RATES.map((r) => (
                    <option key={r} value={r}>
                      {r}%
                    </option>
                  ))}
                </NativeSelect>
                <span className="self-center text-right text-sm tabular-nums">{computed[i] ? formatPaise(computed[i]!.total + computed[i]!.tax) : '—'}</span>
                <Button type="button" variant="ghost" size="icon" aria-label={`Remove item ${i + 1}`} disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}>
                  <Trash2 />
                </Button>
              </div>
            ))}
            <div>
              <Button type="button" variant="outline" size="sm" onClick={() => setLines((ls) => [...ls, blankLine()])}>
                <Plus /> Add item
              </Button>
            </div>
          </CardContent>

          <CardFooter className="flex-col items-stretch gap-4 border-t pt-6 sm:flex-row sm:items-center sm:justify-between">
            <dl className="grid grid-cols-[auto_auto] gap-x-6 gap-y-1 text-sm tabular-nums">
              <dt className="text-muted-foreground">Subtotal</dt>
              <dd className="text-right">{formatPaise(subtotal)}</dd>
              <dt className="text-muted-foreground">GST</dt>
              <dd className="text-right">{formatPaise(tax)}</dd>
              <dt className="font-medium">Total</dt>
              <dd className="text-right font-medium" data-testid="po-total">
                {formatPaise(subtotal + tax)}
              </dd>
            </dl>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" asChild>
                <Link to={po ? `/purchase-orders/${po.po_number}` : '/purchase-orders'}>Cancel</Link>
              </Button>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? 'Saving…' : po ? 'Save changes' : 'Create purchase order'}
              </Button>
            </div>
          </CardFooter>
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
