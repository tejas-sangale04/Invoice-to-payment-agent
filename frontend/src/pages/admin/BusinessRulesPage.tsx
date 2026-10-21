import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/PageHeader'
import { ErrorState, LoadingState } from '@/components/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getBusinessRules, saveBusinessRules } from '@/lib/api'
import { formatPaise, rupeesToPaise } from '@/lib/format'
import type { BusinessRules } from '@/lib/types'

export function BusinessRulesPage() {
  const rules = useQuery({ queryKey: ['business-rules'], queryFn: getBusinessRules })
  if (rules.isPending) return <LoadingState />
  if (rules.isError) return <ErrorState error={rules.error} />
  return <RulesForm initial={rules.data} />
}

function RulesForm({ initial }: { initial: BusinessRules }) {
  const qc = useQueryClient()
  const [tolerance, setTolerance] = useState(initial.price_tolerance_percent)
  const [maxRupees, setMaxRupees] = useState(String(initial.auto_approve_max_paise / 100))
  const [confidence, setConfidence] = useState(initial.min_field_confidence)
  const [formError, setFormError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: saveBusinessRules,
    onSuccess: (data) => {
      qc.setQueryData(['business-rules'], data)
      toast.success('Business rules saved')
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    const paise = rupeesToPaise(maxRupees)
    if (paise === null) return setFormError('Enter the auto-approve limit in rupees, e.g. 50000')
    save.mutate({ price_tolerance_percent: tolerance, auto_approve_max_paise: paise, min_field_confidence: confidence })
  }

  const preview = rupeesToPaise(maxRupees)

  return (
    <>
      <PageHeader title="Business rules" description="The limits the agent's decision step uses. Changes apply to invoices processed from now on." />
      <form onSubmit={onSubmit}>
        <Card>
          <CardContent className="grid gap-6 sm:grid-cols-3">
            <div className="grid content-start gap-2">
              <Label htmlFor="tol">Price tolerance (%)</Label>
              <Input id="tol" inputMode="decimal" required value={tolerance} onChange={(e) => setTolerance(e.target.value)} />
              <p className="text-xs text-muted-foreground">Price differences up to this go to a manager; above it the invoice is held.</p>
            </div>
            <div className="grid content-start gap-2">
              <Label htmlFor="max">Auto-approve limit (₹)</Label>
              <Input id="max" inputMode="decimal" required value={maxRupees} onChange={(e) => setMaxRupees(e.target.value)} />
              <p className="text-xs text-muted-foreground">
                Invoices above {preview === null ? 'this' : formatPaise(preview)} always need a manager.
              </p>
            </div>
            <div className="grid content-start gap-2">
              <Label htmlFor="conf">Minimum extraction confidence (0 to 1)</Label>
              <Input id="conf" inputMode="decimal" required value={confidence} onChange={(e) => setConfidence(e.target.value)} />
              <p className="text-xs text-muted-foreground">Fields read with less confidence than this send the invoice to review.</p>
            </div>
          </CardContent>
          <CardFooter className="justify-end border-t pt-6">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save rules'}
            </Button>
          </CardFooter>
        </Card>
        {(formError || save.isError) && (
          <div className="mt-4">
            <ErrorState error={formError ? new Error(formError) : save.error!} />
          </div>
        )}
      </form>
    </>
  )
}
