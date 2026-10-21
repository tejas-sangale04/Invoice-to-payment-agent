import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { Fragment } from 'react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/States'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatPaise, formatQty } from '@/lib/format'
import type { Invoice, MatchIssueKind } from '@/lib/types'
import { cn } from '@/lib/utils'

// Red only for what blocks payment outright; everything else is amber (needs attention).
const PROBLEM: MatchIssueKind[] = ['duplicate']

/** The 3-way match: each billed line against its PO line and what was received. */
export function MatchCard({ inv }: { inv: Invoice }) {
  const match = inv.match_result
  const generalIssues = match?.issues.filter((i) => i.line === null) ?? []
  const total = inv.extracted?.total_paise

  return (
    <Card className="py-2">
      <CardHeader className="pt-4">
        <CardTitle className="text-base">
          3-way match
          {match?.matched_po && (
            <>
              {' '}
              against{' '}
              <Link to={`/purchase-orders/${match.matched_po}`} className="underline underline-offset-4">
                {match.matched_po}
              </Link>
            </>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 px-2 text-sm">
        {!match && <EmptyState title="Not matched yet" />}

        {generalIssues.length > 0 && (
          <ul className="mx-2 grid gap-2">
            {generalIssues.map((issue) => (
              <li
                key={issue.message}
                className={cn(
                  'flex items-start gap-2 rounded-md border p-3',
                  PROBLEM.includes(issue.kind)
                    ? 'border-destructive/30 bg-destructive/5 text-destructive'
                    : 'border-warning/40 bg-warning/10',
                )}
              >
                <AlertTriangle
                  className={cn('mt-0.5 size-4 shrink-0', !PROBLEM.includes(issue.kind) && 'text-amber-700')}
                />
                {issue.message}
              </li>
            ))}
          </ul>
        )}

        {match && match.per_line.length > 0 && (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Billed</TableHead>
                  <TableHead className="text-right">Can bill</TableHead>
                  <TableHead className="text-right">Price · PO</TableHead>
                  <TableHead className="text-right">GST · PO</TableHead>
                  <TableHead className="text-right">Payable</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {match.per_line.map((l) => (
                  <Fragment key={l.line}>
                    <TableRow className={cn(l.issue && 'border-b-0 bg-warning/10 hover:bg-warning/15')}>
                      <TableCell className="whitespace-normal">
                        <span className="font-medium">{l.name}</span>
                        {l.po_item_name && l.po_item_name !== l.name && (
                          <p className="text-xs text-muted-foreground">PO: {l.po_item_name}</p>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatQty(l.billed_qty)} {l.unit}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {l.po_line_id ? (
                          <>
                            {formatQty(l.available_qty)}
                            <p className="text-xs text-muted-foreground">received {formatQty(l.received_qty)}</p>
                            {Number(l.already_billed_qty) > 0 && (
                              <p className="text-xs text-muted-foreground">billed {formatQty(l.already_billed_qty)}</p>
                            )}
                          </>
                        ) : (
                          '—'
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatPaise(l.billed_unit_price_paise)}
                        {l.po_unit_price_paise !== null && (
                          <p className="text-xs text-muted-foreground">{formatPaise(l.po_unit_price_paise)}</p>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatQty(l.billed_tax_rate)}%
                        {l.po_tax_rate !== null && (
                          <p className="text-xs text-muted-foreground">{formatQty(l.po_tax_rate)}%</p>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatPaise(l.correct_amount_paise)}</TableCell>
                    </TableRow>
                    {l.issue && (
                      <TableRow className="bg-warning/10 hover:bg-warning/15">
                        <TableCell colSpan={6} className="pt-0 whitespace-normal text-xs text-amber-700">
                          {l.issue}
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
            <p className="px-2 text-xs text-muted-foreground">
              Can bill = received minus what other invoices already bill. Payable is before GST, at no more than the PO
              price.
            </p>
            <dl className="ml-auto grid grid-cols-[auto_auto] gap-x-6 gap-y-1 px-2 tabular-nums">
              {total != null && (
                <>
                  <dt className="text-muted-foreground">Invoice total</dt>
                  <dd className="text-right">{formatPaise(total)}</dd>
                </>
              )}
              <dt className="text-muted-foreground">Correct amount (with GST)</dt>
              <dd className="text-right">{formatPaise(match.correct_amount_paise)}</dd>
              <dt className="font-medium">Difference</dt>
              <dd className={cn('text-right font-medium', match.difference_paise > 0 && 'text-destructive')}>
                {match.difference_paise > 0 && '+'}
                {formatPaise(match.difference_paise)}
              </dd>
            </dl>
            {match.issues.length === 0 && (
              <p className="flex items-center gap-2 px-2 text-green-700">
                <CheckCircle2 className="size-4" /> Quantities, prices and GST all match.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
