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

// Pipeline steps in the order they run.
const STEPS = [
  ['start', 'Duplicate file check'],
  ['extract', 'Reading (Gemini)'],
  ['validate', 'Checks'],
  ['match', 'Matching'],
  ['decide', 'Decision'],
  ['post', 'Posting'],
] as const

const AXIS = { fill: 'var(--muted-foreground)', fontSize: 12 }
const LABEL = { fill: 'var(--foreground)', fontSize: 12 }

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card className="gap-1 py-4">
      <CardHeader className="px-4">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
      </CardHeader>
    </Card>
  )
}

function seconds(s: number | null | undefined): string {
  if (s == null) return '—'
  return s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`
}

/** One series, so a single neutral hue; the axis labels name each bar. */
function HBars({ data, unit }: { data: { label: string; value: number }[]; unit: string }) {
  return (
    <div style={{ height: data.length * 36 + 32 }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24 }}>
          <CartesianGrid horizontal={false} stroke="var(--border)" />
          <XAxis
            type="number"
            allowDecimals={unit !== 'Invoices'}
            tick={AXIS}
            tickFormatter={unit === 's' ? (v: number) => seconds(v) : undefined}
            axisLine={false}
            tickLine={false}
          />
          <YAxis type="category" dataKey="label" width={140} tick={LABEL} axisLine={false} tickLine={false} />
          <Tooltip cursor={{ fill: 'var(--muted)' }} formatter={(v) => [unit === 's' ? seconds(Number(v)) : v, unit === 's' ? 'Average' : unit]} />
          <Bar dataKey="value" fill="var(--primary)" radius={[0, 4, 4, 0]} barSize={16} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function DashboardPage() {
  const live = FEATURES.dashboard.live
  const metrics = useQuery({ queryKey: ['dashboard'], queryFn: getDashboardMetrics, enabled: live, refetchInterval: 30_000 })
  const m = metrics.data
  const dash = '—'
  const decisions = DECISIONS.map(([key, label]) => ({ label, value: m?.decision_counts[key] ?? 0 }))
  const steps = STEPS.filter(([key]) => m?.avg_step_seconds[key] != null).map(([key, label]) => ({
    label,
    value: m!.avg_step_seconds[key],
  }))
  const daily = (m?.daily ?? []).map((d) => ({
    label: new Date(`${d.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
    value: d.uploaded,
  }))

  return (
    <>
      <PageHeader title="Dashboard" description="Figures come only from invoices actually processed." />
      {!live && <NotLiveNotice feature="dashboard" />}
      {live && metrics.isPending && <LoadingState />}
      {metrics.isError && <ErrorState error={metrics.error} />}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Invoices processed"
          value={m ? String(m.invoices_processed) : dash}
          note={m ? `${m.invoices_uploaded} uploaded · ${m.waiting_for_approval} waiting for approval` : undefined}
        />
        <Stat
          label="Posted for payment"
          value={m ? formatPaise(m.posted_paise) : dash}
          note={m ? `${m.posted_count} invoice${m.posted_count === 1 ? '' : 's'}` : undefined}
        />
        <Stat label="Overcharges caught" value={m ? formatPaise(m.money_saved_paise) : dash} note="On held invoices, and paid at the PO price" />
        <Stat
          label="Duplicates blocked"
          value={m ? formatPaise(m.duplicates_blocked_paise) : dash}
          note={m ? `${m.duplicates_blocked} invoice${m.duplicates_blocked === 1 ? '' : 's'}` : undefined}
        />
        <Stat label="Avg processing time" value={seconds(m?.avg_processing_seconds)} note="Upload to decision" />
        <Stat
          label="Avg AI cost per invoice"
          value={m?.avg_ai_cost_paise != null ? `₹${(m.avg_ai_cost_paise / 100).toFixed(2)}` : dash}
          note="Estimated from tokens used"
        />
        <Stat
          label="Avg tokens per invoice"
          value={m?.avg_tokens != null ? Math.round(m.avg_tokens).toLocaleString('en-IN') : dash}
          note={m?.avg_ai_calls != null ? `${m.avg_ai_calls.toFixed(1)} model calls · ${seconds(m.avg_ai_latency_seconds)} in Gemini` : undefined}
        />
        <Stat label="Needed a retry" value={m ? String(m.retried_invoices) : dash} note="More than one processing attempt" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Decisions</CardTitle>
          </CardHeader>
          <CardContent>
            {!m || m.invoices_processed === 0 ? <EmptyState title="No decisions yet" /> : <HBars data={decisions} unit="Invoices" />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Average time per step</CardTitle>
            <CardDescription>Summed over retries and reprocessing</CardDescription>
          </CardHeader>
          <CardContent>{steps.length === 0 ? <EmptyState title="Nothing processed yet" /> : <HBars data={steps} unit="s" />}</CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-base">Invoices uploaded per day</CardTitle>
          <CardDescription>Last 14 days</CardDescription>
        </CardHeader>
        <CardContent>
          {!m || m.invoices_uploaded === 0 ? (
            <EmptyState title="No invoices yet" />
          ) : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={daily} margin={{ left: 0, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                  <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} width={32} />
                  <Tooltip cursor={{ fill: 'var(--muted)' }} formatter={(v) => [v, 'Invoices']} />
                  <Bar dataKey="value" fill="var(--primary)" radius={[4, 4, 0, 0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
      {m && <p className="mt-4 text-xs text-muted-foreground">AI cost uses {m.ai_price_note}. Set the prices in the backend settings.</p>}
    </>
  )
}
