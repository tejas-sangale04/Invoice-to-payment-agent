import { AlertCircle, Construction, Inbox, Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'

import { FEATURES, type Feature } from '@/lib/features'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  )
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <div role="alert" className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
      <AlertCircle className="size-4 shrink-0" /> {error.message}
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <Inbox className="size-8 text-muted-foreground" />
      <p className="font-medium">{title}</p>
      {children && <div className="text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}

/** Shown on screens whose backend arrives in a later build phase. */
export function NotLiveNotice({ feature, children }: { feature: Feature; children?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start gap-3 rounded-md border border-warning/40 bg-warning/10 p-4 text-sm">
      <Construction className="mt-0.5 size-4 shrink-0 text-amber-700" />
      <div>
        <p className="font-medium">This screen is ready, but its backend comes in Phase {FEATURES[feature].phase}.</p>
        {children && <p className="text-muted-foreground">{children}</p>}
      </div>
    </div>
  )
}
