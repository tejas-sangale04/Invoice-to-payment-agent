import { AlertTriangle } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatDate, formatPaise, formatQty } from '@/lib/format'
import type { Invoice } from '@/lib/types'

function Field({ label, value, confidence }: { label: string; value: string | null | undefined; confidence?: number }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">
        {label}
        {confidence !== undefined && <span className="ml-1 tabular-nums">· {Math.round(confidence * 100)}% sure</span>}
      </dt>
      <dd className="font-medium">{value || '—'}</dd>
    </div>
  )
}

/** What the Extraction Agent read, after code converted it, plus any checks that failed. */
export function ExtractedCard({ inv }: { inv: Invoice }) {
  const e = inv.extracted
  const conf = e?.field_confidence ?? {}
  const money = (p: number | null | undefined) => (p == null ? null : formatPaise(p))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Extracted details</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        {inv.validation_issues.length > 0 && (
          <div className="rounded-md border border-warning/40 bg-warning/10 p-3">
            <p className="mb-1 flex items-center gap-2 font-medium">
              <AlertTriangle className="size-4 text-amber-700" /> Checks that didn't pass
            </p>
            <ul className="list-disc pl-6">
              {inv.validation_issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
        {!e && <p className="text-muted-foreground">Not read yet.</p>}
        <dl className="grid grid-cols-2 gap-4">
          <Field label="File" value={`${inv.file_name} (${Math.ceil(inv.file_size / 1024)} KB)`} />
          <Field label="Supplier" value={e?.supplier_name} confidence={conf.supplier_name} />
          <Field label="Invoice number" value={e?.invoice_no} confidence={conf.invoice_no} />
          <Field label="Invoice date" value={e?.invoice_date && formatDate(e.invoice_date)} confidence={conf.invoice_date} />
          <Field label="PO number" value={e?.po_number} confidence={conf.po_number} />
          <Field label="Supplier GSTIN" value={e?.supplier_gstin} />
        </dl>

        {e && e.items.length > 0 && (
          <div className="-mx-2">
            <p className="px-2 text-xs text-muted-foreground">
              Line items{conf.line_items !== undefined && ` · ${Math.round(conf.line_items * 100)}% sure`}
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Unit price</TableHead>
                  <TableHead className="text-right">GST</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {e.items.map((item, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium whitespace-normal">{item.name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatQty(item.qty)} {item.unit}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatPaise(item.unit_price_paise)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatQty(item.tax_rate)}%</TableCell>
                    <TableCell className="text-right tabular-nums">{money(item.amount_paise) ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {e && (
          <dl className="ml-auto grid grid-cols-[auto_auto] gap-x-6 gap-y-1 tabular-nums">
            {conf.totals !== undefined && (
              <dd className="col-span-2 text-right text-xs text-muted-foreground">Totals · {Math.round(conf.totals * 100)}% sure</dd>
            )}
            <dt className="text-muted-foreground">Subtotal</dt>
            <dd className="text-right">{money(e.subtotal_paise) ?? '—'}</dd>
            {e.igst_paise > 0 ? (
              <>
                <dt className="text-muted-foreground">IGST</dt>
                <dd className="text-right">{formatPaise(e.igst_paise)}</dd>
              </>
            ) : (
              <>
                <dt className="text-muted-foreground">CGST</dt>
                <dd className="text-right">{formatPaise(e.cgst_paise)}</dd>
                <dt className="text-muted-foreground">SGST</dt>
                <dd className="text-right">{formatPaise(e.sgst_paise)}</dd>
              </>
            )}
            <dt className="font-medium">Total</dt>
            <dd className="text-right font-medium">{money(e.total_paise) ?? '—'}</dd>
          </dl>
        )}

        {inv.ai_usage && inv.ai_usage.calls > 0 && (
          <p className="text-xs text-muted-foreground">
            Read by the agent in {inv.ai_usage.calls} call{inv.ai_usage.calls > 1 ? 's' : ''} ·{' '}
            {(inv.ai_usage.input_tokens + inv.ai_usage.output_tokens).toLocaleString('en-IN')} tokens ·{' '}
            {(inv.ai_usage.latency_ms / 1000).toFixed(1)} s
          </p>
        )}
      </CardContent>
    </Card>
  )
}
