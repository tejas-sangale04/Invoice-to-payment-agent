const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 })

/** 405000 -> "₹4,050.00" */
export function formatPaise(paise: number): string {
  return inr.format(paise / 100)
}

/** "60" -> 6000, "60.5" -> 6050. Returns null for anything that isn't a valid rupee amount. */
export function rupeesToPaise(input: string): number | null {
  const m = /^\s*(\d{1,10})(?:\.(\d{0,2}))?\s*$/.exec(input)
  if (!m) return null
  return Number(m[1]) * 100 + Number((m[2] ?? '').padEnd(2, '0'))
}

/** Decimal string to integer thousandths, e.g. "2.5" -> 2500n. Null if invalid. */
function toMilli(input: string): bigint | null {
  const m = /^\s*(\d{1,9})(?:\.(\d{0,3}))?\s*$/.exec(input)
  if (!m) return null
  return BigInt(m[1]) * 1000n + BigInt((m[2] ?? '').padEnd(3, '0'))
}

/** Divide and round half up (all values are non-negative). */
function roundDiv(n: bigint, d: bigint): bigint {
  return (n * 2n + d) / (2n * d)
}

/**
 * Same arithmetic as backend/app/pipeline/money.py, for the live total on the PO form.
 * The backend's figure is the one that counts. Returns null if any input is invalid.
 */
export function lineAmounts(qty: string, unitPricePaise: number, taxRate: string) {
  const q = toMilli(qty)
  const r = toMilli(taxRate || '0') // percent in thousandths
  if (q === null || r === null) return null
  const taxableMilli = q * BigInt(unitPricePaise) // paise * 1000
  const total = roundDiv(taxableMilli, 1000n)
  const tax = roundDiv(taxableMilli * r, 1000n * 1000n * 100n)
  return { total: Number(total), tax: Number(tax) }
}

export function formatQty(qty: string): string {
  return qty.includes('.') ? qty.replace(/\.?0+$/, '') : qty
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function remainingQty(ordered: string, received: string): string {
  const o = toMilli(ordered) ?? 0n
  const r = toMilli(received) ?? 0n
  const left = o - r
  const whole = left / 1000n
  const frac = (left % 1000n).toString().padStart(3, '0').replace(/0+$/, '')
  return frac ? `${whole}.${frac}` : `${whole}`
}
