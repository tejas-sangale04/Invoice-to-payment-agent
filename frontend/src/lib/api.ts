import { auth } from '@/lib/firebase'
import type {
  AuditEntry,
  BusinessRules,
  EmailStatus,
  GoodsReceipt,
  Invoice,
  InvoiceStatus,
  LedgerEntry,
  Page,
  POStatus,
  PurchaseOrder,
  Supplier,
} from '@/lib/types'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Role = 'staff' | 'manager' | 'admin'

export interface Me {
  uid: string
  email: string | null
  role: Role | null
}

/** Matches the backend's error shape: {"error": {"code", "message", "details"}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** Fetch from the backend with the current user's Firebase ID token attached. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await auth.currentUser?.getIdToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')

  const res = await fetch(`${API_URL}${path}`, { ...init, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.error?.code ?? 'error', body?.error?.message ?? res.statusText)
  }
  return res.json() as Promise<T>
}

export const getMe = () => apiFetch<Me>('/me')

// ---- Endpoints ----

function qs(params: Record<string, string | number | undefined | null>): string {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const listSuppliers = (limit = 100) => apiFetch<Page<Supplier>>(`/suppliers${qs({ limit })}`)
export const createSupplier = (body: { name: string; email: string; gstin?: string }) =>
  apiFetch<Supplier>('/suppliers', { method: 'POST', body: JSON.stringify(body) })

export const listPurchaseOrders = (params: { status?: POStatus; cursor?: string | null; limit?: number } = {}) =>
  apiFetch<Page<PurchaseOrder>>(`/purchase-orders${qs({ limit: params.limit ?? 50, ...params })}`)
export const getPurchaseOrder = (po: string) => apiFetch<PurchaseOrder>(`/purchase-orders/${encodeURIComponent(po)}`)
export interface POItemInput {
  name: string
  qty: string
  unit: string
  unit_price_paise: number
  tax_rate: string
}
export const createPurchaseOrder = (body: { supplier_id: string; items: POItemInput[] }) =>
  apiFetch<PurchaseOrder>('/purchase-orders', { method: 'POST', body: JSON.stringify(body) })

export const listGoodsReceipts = (poNumber?: string) =>
  apiFetch<Page<GoodsReceipt>>(`/goods-receipts${qs({ po_number: poNumber, limit: 100 })}`)
export const createGoodsReceipt = (body: {
  po_number: string
  received_on: string
  notes: string
  items: { line_id: string; qty_received: string }[]
}) => apiFetch<GoodsReceipt>('/goods-receipts', { method: 'POST', body: JSON.stringify(body) })

export const getBusinessRules = () => apiFetch<BusinessRules>('/business-rules')
export const saveBusinessRules = (body: BusinessRules) =>
  apiFetch<BusinessRules>('/business-rules', { method: 'PUT', body: JSON.stringify(body) })

// ---- Invoice endpoints (Setup guide, Section 9). Screens only call these once FEATURES says they're live. ----

export interface DashboardMetrics {
  invoices_uploaded: number
  invoices_processed: number
  decision_counts: Record<string, number>
  status_counts: Record<string, number>
  waiting_for_approval: number
  posted_count: number
  posted_paise: number
  money_saved_paise: number
  duplicates_blocked: number
  duplicates_blocked_paise: number
  avg_processing_seconds: number | null
  avg_step_seconds: Record<string, number>
  avg_ai_calls: number | null
  avg_tokens: number | null
  avg_ai_latency_seconds: number | null
  avg_ai_cost_paise: number | null
  ai_price_note: string
  retried_invoices: number
  daily: { date: string; uploaded: number; decided: number }[]
}

export const listInvoices = (params: { status?: InvoiceStatus; cursor?: string | null } = {}) =>
  apiFetch<Page<Invoice>>(`/invoices${qs({ limit: 50, ...params })}`)
export const getInvoice = (id: string) => apiFetch<Invoice>(`/invoices/${encodeURIComponent(id)}`)
export const getInvoiceFileUrl = (id: string) =>
  apiFetch<{ url: string; content_type: string; expires_in_seconds: number }>(`/invoices/${encodeURIComponent(id)}/file`)
export const uploadInvoice = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return apiFetch<Invoice>('/invoices', { method: 'POST', body })
}
export const approveInvoice = (id: string, comment: string) =>
  apiFetch<Invoice>(`/invoices/${encodeURIComponent(id)}/approve`, { method: 'POST', body: JSON.stringify({ comment }) })
export interface SupplierEmailInput {
  subject: string
  body: string
}
export const rejectInvoice = (id: string, reason: string, email?: SupplierEmailInput) =>
  apiFetch<Invoice>(`/invoices/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    body: JSON.stringify(email ? { reason, email } : { reason }),
  })
export const emailSupplier = (id: string, email: SupplierEmailInput) =>
  apiFetch<Invoice>(`/invoices/${encodeURIComponent(id)}/email-supplier`, { method: 'POST', body: JSON.stringify(email) })
export const draftSupplierEmail = (id: string, rejected: boolean) =>
  apiFetch<{ email: string; source: string }>(`/invoices/${encodeURIComponent(id)}/email-draft${qs({ rejected: rejected ? 'true' : undefined })}`, {
    method: 'POST',
  })
export const getEmailStatus = () => apiFetch<EmailStatus>('/email-status')
export const reprocessInvoice = (id: string) =>
  apiFetch<Invoice>(`/invoices/${encodeURIComponent(id)}/reprocess`, { method: 'POST' })
export const getAuditLog = (invoiceId: string) =>
  apiFetch<Page<AuditEntry>>(`/audit-log${qs({ invoice_id: invoiceId })}`)
export const listLedger = () => apiFetch<Page<LedgerEntry>>('/ledger?limit=100')
export const getDashboardMetrics = () => apiFetch<DashboardMetrics>('/dashboard/metrics')
