import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileUp, X } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { ErrorState, NotLiveNotice } from '@/components/States'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { getInvoice, uploadInvoice } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import type { Invoice, InvoiceStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

const ACCEPTED = ['application/pdf', 'image/png', 'image/jpeg']
const MAX_BYTES = 10 * 1024 * 1024

const PROCESSING: InvoiceStatus[] = ['received', 'extracting', 'extracted', 'validated', 'matched']

/** Shows the uploaded invoice's status, polling until the agent is done with it. */
function UploadedStatus({ uploaded }: { uploaded: Invoice }) {
  const inv = useQuery({
    queryKey: ['invoice', uploaded.invoice_id],
    queryFn: () => getInvoice(uploaded.invoice_id),
    initialData: uploaded,
    refetchInterval: (q) => (q.state.data && PROCESSING.includes(q.state.data.status) ? 1500 : false),
  }).data
  return (
    <div className="grid gap-1 rounded-md border p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span>
          <span className="font-medium">{inv.invoice_id}</span> · {inv.file_name}
        </span>
        <div className="flex items-center gap-3">
          <StatusBadge status={inv.status} />
          <Link to={`/invoices/${inv.invoice_id}`} className="underline">
            View
          </Link>
        </div>
      </div>
      {inv.status_reason && <p className="text-muted-foreground">{inv.status_reason}</p>}
    </div>
  )
}

export function UploadInvoicePage() {
  const live = FEATURES.invoices.live
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: uploadInvoice,
    onSuccess: () => {
      toast.success('Invoice uploaded. The agent is checking it now.')
      qc.invalidateQueries({ queryKey: ['invoices'] })
      setFile(null)
    },
  })

  function pick(f: File | undefined) {
    setFileError(null)
    mutation.reset()
    if (!f) return
    if (!ACCEPTED.includes(f.type)) return setFileError('Upload a PDF, PNG or JPEG file.')
    if (f.size > MAX_BYTES) return setFileError('Files must be 10 MB or smaller.')
    setFile(f)
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (live) pick(e.dataTransfer.files[0])
  }

  return (
    <>
      <PageHeader title="Upload invoice" description="Drop a supplier invoice. The agent reads it, matches it to the PO and deliveries, and decides what happens next." />
      {!live && <NotLiveNotice feature="invoices">Upload is switched off until invoice intake is built.</NotLiveNotice>}
      <Card>
        <CardContent className="grid gap-4">
          <div
            role="button"
            tabIndex={live ? 0 : -1}
            aria-disabled={!live}
            onClick={() => live && input.current?.click()}
            onKeyDown={(e) => live && (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              if (live) setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors',
              live ? 'cursor-pointer hover:border-ring' : 'cursor-not-allowed opacity-60',
              dragging && 'border-ring bg-accent',
            )}
          >
            <FileUp className="size-8 text-muted-foreground" />
            <p className="font-medium">Drag an invoice here, or click to choose a file</p>
            <p className="text-sm text-muted-foreground">PDF, PNG or JPEG, up to 10 MB</p>
            <input ref={input} type="file" accept={ACCEPTED.join(',')} className="hidden" disabled={!live} onChange={(e) => pick(e.target.files?.[0])} />
          </div>

          {file && (
            <div className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm">
              <span className="truncate">
                {file.name} <span className="text-muted-foreground">({(file.size / 1024).toFixed(0)} KB)</span>
              </span>
              <div className="flex shrink-0 gap-2">
                <Button size="sm" variant="ghost" aria-label="Remove file" onClick={() => setFile(null)}>
                  <X />
                </Button>
                <Button size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate(file)}>
                  {mutation.isPending ? 'Uploading…' : 'Upload'}
                </Button>
              </div>
            </div>
          )}
          {fileError && <ErrorState error={new Error(fileError)} />}
          {mutation.isError && <ErrorState error={mutation.error} />}
          {mutation.data && <UploadedStatus key={mutation.data.invoice_id} uploaded={mutation.data} />}
        </CardContent>
      </Card>
    </>
  )
}
