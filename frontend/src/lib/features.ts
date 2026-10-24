// Screens whose backend is not built yet render their layout with an explanatory notice and
// make no API calls. Flip a flag to true when its phase lands.
export const FEATURES = {
  invoices: { live: true, phase: 3 },
  approvals: { live: true, phase: 6 },
  ledger: { live: true, phase: 6 },
  dashboard: { live: true, phase: 8 },
} as const

export type Feature = keyof typeof FEATURES
