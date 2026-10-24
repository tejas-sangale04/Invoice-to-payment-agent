import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'

import { useAuth } from '@/auth/AuthProvider'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '@/components/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { createSupplier, listSuppliers, updateSupplier } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { hasRole } from '@/lib/roles'
import type { Supplier } from '@/lib/types'

function AddSupplierForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [gstin, setGstin] = useState('')
  const mutation = useMutation({
    mutationFn: createSupplier,
    onSuccess: (s) => {
      toast.success(`Added ${s.name} (${s.supplier_id})`)
      qc.invalidateQueries({ queryKey: ['suppliers'] })
      onDone()
    },
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    mutation.mutate({ name, email, gstin: gstin || undefined })
  }

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle className="text-base">New supplier</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-3">
          <div className="grid gap-2">
            <Label htmlFor="s-name">Name</Label>
            <Input id="s-name" required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="s-email">Accounts email</Label>
            <Input id="s-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="s-gstin">GSTIN (optional)</Label>
            <Input id="s-gstin" maxLength={15} placeholder="27ABCDE1234F1Z5" value={gstin} onChange={(e) => setGstin(e.target.value)} />
          </div>
          {mutation.isError && (
            <div className="sm:col-span-3">
              <ErrorState error={mutation.error} />
            </div>
          )}
          <div className="flex gap-2 sm:col-span-3">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Saving…' : 'Add supplier'}
            </Button>
            <Button type="button" variant="ghost" onClick={onDone}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function EditSupplierForm({ supplier, onDone }: { supplier: Supplier; onDone: () => void }) {
  const qc = useQueryClient()
  const [email, setEmail] = useState(supplier.email)
  const [gstin, setGstin] = useState(supplier.gstin ?? '')
  const mutation = useMutation({
    mutationFn: () => updateSupplier(supplier.supplier_id, { email, gstin: gstin.trim() || null }),
    onSuccess: (s) => {
      toast.success(`Saved ${s.name}`)
      qc.invalidateQueries({ queryKey: ['suppliers'] })
      onDone()
    },
  })

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle className="text-base">
          Edit {supplier.name} ({supplier.supplier_id})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            mutation.mutate()
          }}
          className="grid gap-4 sm:grid-cols-2"
        >
          <div className="grid gap-2">
            <Label htmlFor="e-email">Accounts email</Label>
            <Input id="e-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="e-gstin">GSTIN (optional)</Label>
            <Input id="e-gstin" maxLength={15} placeholder="27ABCDE1234F1Z5" value={gstin} onChange={(e) => setGstin(e.target.value)} />
          </div>
          {mutation.isError && (
            <div className="sm:col-span-2">
              <ErrorState error={mutation.error} />
            </div>
          )}
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Saving…' : 'Save changes'}
            </Button>
            <Button type="button" variant="ghost" onClick={onDone}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

export function SuppliersPage() {
  const { role } = useAuth()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<Supplier | null>(null)
  const suppliers = useQuery({ queryKey: ['suppliers'], queryFn: () => listSuppliers() })
  const isAdmin = hasRole(role, 'admin')

  return (
    <>
      <PageHeader
        title="Suppliers"
        description={isAdmin ? 'Suppliers you buy from.' : 'Suppliers you buy from. Only admins can add suppliers.'}
        actions={
          isAdmin &&
          !adding && (
            <Button onClick={() => setAdding(true)}>
              <Plus /> Add supplier
            </Button>
          )
        }
      />
      {adding && <AddSupplierForm onDone={() => setAdding(false)} />}
      {editing && <EditSupplierForm key={editing.supplier_id} supplier={editing} onDone={() => setEditing(null)} />}
      <Card className="py-2">
        <CardContent className="px-2">
          {suppliers.isPending && <LoadingState />}
          {suppliers.isError && <ErrorState error={suppliers.error} />}
          {suppliers.data?.items.length === 0 && <EmptyState title="No suppliers yet" />}
          {!!suppliers.data?.items.length && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>GSTIN</TableHead>
                  <TableHead>Added</TableHead>
                  {isAdmin && <TableHead className="w-12" />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {suppliers.data.items.map((s) => (
                  <TableRow key={s.supplier_id}>
                    <TableCell className="font-mono text-xs">{s.supplier_id}</TableCell>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell>{s.email}</TableCell>
                    <TableCell className="font-mono text-xs">{s.gstin ?? '—'}</TableCell>
                    <TableCell>{formatDate(s.created_at)}</TableCell>
                    {isAdmin && (
                      <TableCell>
                        <Button variant="ghost" size="icon" aria-label={`Edit ${s.name}`} onClick={() => { setAdding(false); setEditing(s) }}>
                          <Pencil />
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  )
}
