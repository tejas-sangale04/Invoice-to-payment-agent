import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { PageHeader } from '@/components/PageHeader'
import { EmptyState, ErrorState, LoadingState, NotLiveNotice } from '@/components/States'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getDashboardMetrics } from '@/lib/api'
import { FEATURES } from '@/lib/features'
import { formatPaise } from '@/lib/format'

const DECISIONS = [
  ['auto_approve', 'Auto-approved'],
  ['manager_approval', 'Manager approval'],
  ['hold', 'On hold'],
  ['block', 'Blocked'],
  ['needs_review', 'Needs review'],
] as const

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="gap-1 py-4">
      <CardHeader className="px-4">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
    </Card>
  )
}

export function DashboardPage() {
  const live = FEATURES.dashboard.live
  const metrics = useQuery({ queryKey: ['dashboard'], queryFn: getDashboardMetrics, enabled: live })
  const m = metrics.data
  const dash = '—'
  // One series, so a single neutral hue; the axis labels name each bar.
  const decisions = DECISIONS.map(([key, label]) => ({ label, count: m?.decision_counts[key] ?? 0 }))

  return (
    <>
      <PageHeader title="Dashboard" description="Figures come only from invoices actually processed." />
      {!live && <NotLiveNotice feature="dashboard" />}
      {live && metrics.isPending && <LoadingState />}
      {metrics.isError && <ErrorState error={metrics.error} />}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Invoices processed" value={m ? String(m.invoices_processed) : dash} />
        <Stat label="Money saved by holds" value={m ? formatPaise(m.money_saved_paise) : dash} />
        <Stat label="Avg processing time" value={m?.avg_processing_seconds != null ? `${m.avg_processing_seconds.toFixed(1)} s` : dash} />
        <Stat label="Avg AI cost per invoice" value={m?.avg_ai_cost_paise != null ? formatPaise(m.avg_ai_cost_paise) : dash} />
      </div>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-base">Decisions</CardTitle>
        </CardHeader>
        <CardContent>
          {!m || m.invoices_processed === 0 ? (
            <EmptyState title="No decisions yet" />
          ) : (
            <div className="h-64">
              <ResponsiveContainer>
                <BarChart data={decisions} layout="vertical" margin={{ left: 24, right: 24 }}>
                  <CartesianGrid horizontal={false} stroke="var(--border)" />
                  <XAxis type="number" allowDecimals={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="label" width={120} tick={{ fill: 'var(--foreground)', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: 'var(--muted)' }} formatter={(v) => [v, 'Invoices']} />
                  <Bar dataKey="count" fill="var(--primary)" radius={[0, 4, 4, 0]} barSize={18} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}
