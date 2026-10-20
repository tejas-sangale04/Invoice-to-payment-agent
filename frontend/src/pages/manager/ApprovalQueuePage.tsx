import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { useAuth } from '@/auth/AuthProvider'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState, NotLiveNotice } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { approveInvoice, listInvoices, rejectInvoice } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import { formatPaise } from '@/lib/format'
import type { Invoice } from '@/lib/types'

function ApprovalCard({ inv }: { inv: Invoice }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')
  const ownUpload = inv.uploaded_by === user?.uid
  const done = (verb: string) => () => {
    toast.success(`Invoice ${inv.invoice_no ?? inv.invoice_id} ${verb}`)
    qc.invalidateQueries({ queryKey: ['invoices'] })
  }
  const approve = useMutation({ mutationFn: () => approveInvoice(inv.invoice_id, comment), onSuccess: done('approved') })
  const reject = useMutation({ mutationFn: () => rejectInvoice(inv.invoice_id, comment), onSuccess: done('rejected') })
  const diff = inv.match_result?.difference_paise ?? 0

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <CardTitle className="text-base">
            <Link to={`/invoices/${inv.invoice_id}`} className="hover:underline">
              {inv.supplier_name} · {inv.invoice_no}
            </Link>
          </CardTitle>
          <p className="text-sm text-muted-foreground">{inv.po_number ?? 'No PO number'}</p>
        </div>
        {inv.decision && <StatusBadge status={inv.decision} />}
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <dl className="grid grid-cols-3 gap-4">
          <div>
            <dt className="text-xs text-muted-foreground">Billed</dt>
            <dd className="text-lg font-semibold tabular-nums">{inv.total_paise == null ? '—' : formatPaise(inv.total_paise)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Correct amount</dt>
            <dd className="text-lg font-semibold tabular-nums">{inv.match_result ? formatPaise(inv.match_result.correct_amount_paise) : '—'}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Difference</dt>
            <dd className={`text-lg font-semibold tabular-nums ${diff !== 0 ? 'text-destructive' : ''}`}>{formatPaise(diff)}</dd>
          </div>
        </dl>
        {inv.decision_reason && <p>{inv.decision_reason}</p>}
        <Textarea aria-label="Comment" placeholder="Comment (required to reject)" value={comment} onChange={(e) => setComment(e.target.value)} />
        {ownUpload && <p className="text-amber-700">You uploaded this invoice, so another manager has to approve it.</p>}
        {(approve.isError || reject.isError) && <ErrorState error={(approve.error ?? reject.error)!} />}
      </CardContent>
      <CardFooter className="justify-end gap-2">
        <Button variant="outline" disabled={ownUpload || !comment.trim() || reject.isPending} onClick={() => reject.mutate()}>
          <X /> Reject
        </Button>
        <Button disabled={ownUpload || approve.isPending} onClick={() => approve.mutate()}>
          <Check /> Approve
        </Button>
      </CardFooter>
    </Card>
  )
}

export function ApprovalQueuePage() {
  const live = FEATURES.approvals.live
  const queue = useQuery({ queryKey: ['invoices', 'pending_approval'], queryFn: () => listInvoices({ status: 'pending_approval' }), enabled: live })

  return (
    <>
      <PageHeader title="Approval queue" description="Invoices the agent sent for a manager decision." />
      {!live && <NotLiveNotice feature="approvals" />}
      {!live && (
        <Card>
          <EmptyState title="Nothing waiting for approval" />
        </Card>
      )}
      {live && queue.isPending && <LoadingState />}
      {queue.isError && <ErrorState error={queue.error} />}
      {queue.data?.items.length === 0 && (
        <Card>
          <EmptyState title="Nothing waiting for approval" />
        </Card>
      )}
      <div className="grid gap-4">
        {queue.data?.items.map((inv) => <ApprovalCard key={inv.invoice_id} inv={inv} />)}
      </div>
    </>
  )
}
