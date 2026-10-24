// Mirrors the backend's Pydantic models. Decimal fields (qty, tax_rate) arrive as strings.
export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export interface Supplier {
  supplier_id: string
  name: string
  normalized_name: string
  email: string
  gstin: string | null
  created_at: string
}

export type POStatus = 'open' | 'partially_billed' | 'fully_billed' | 'closed'

export interface POLine {
  line_id: string
  name: string
  qty: string
  unit: string
  unit_price_paise: number
  tax_rate: string
  qty_received: string
  qty_billed: string
  line_total_paise: number
  tax_paise: number
}

export interface PurchaseOrder {
  po_number: string
  supplier_id: string
  supplier_name: string
  status: POStatus
  items: POLine[]
  subtotal_paise: number
  tax_paise: number
  total_paise: number
  created_by: string
  created_at: string
}

export interface GoodsReceipt {
  gr_id: string
  po_number: string
  items: { line_id: string; qty_received: string }[]
  received_by: string
  received_on: string
  notes: string
  created_at: string
}

export interface BusinessRules {
  price_tolerance_percent: string
  auto_approve_max_paise: number
  min_field_confidence: string
}

// ---- Invoices (setup guide, Section 5) ----

export type InvoiceStatus =
  | 'received'
  | 'extracting'
  | 'extracted'
  | 'validated'
  | 'matched'
  | 'auto_approved'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'posted'
  | 'paid'
  | 'on_hold'
  | 'blocked_duplicate'
  | 'needs_review'
  | 'failed'

export type Decision = 'auto_approve' | 'manager_approval' | 'hold' | 'block' | 'needs_review'

export type MatchIssueKind =
  | 'duplicate'
  | 'supplier'
  | 'no_po'
  | 'unmatched_line'
  | 'unit'
  | 'quantity'
  | 'price_over_tolerance'
  | 'price_within_tolerance'
  | 'gst_rate'
  | 'possible_duplicate'

export interface MatchIssue {
  kind: MatchIssueKind
  message: string
  line: number | null
}

export interface MatchLine {
  line: number
  name: string
  po_line_id: string | null
  po_item_name: string | null
  unit: string | null
  billed_qty: string
  received_qty: string
  already_billed_qty: string
  available_qty: string
  billed_unit_price_paise: number
  po_unit_price_paise: number | null
  billed_tax_rate: string
  po_tax_rate: string | null
  billed_amount_paise: number
  correct_amount_paise: number
  issue: string | null
}

export interface MatchResult {
  matched_po: string | null
  supplier_id: string | null
  matched_without_po_number: boolean
  per_line: MatchLine[]
  issues: MatchIssue[]
  correct_amount_paise: number
  difference_paise: number
}

export interface Extracted {
  supplier_name: string | null
  supplier_gstin: string | null
  invoice_no: string | null
  invoice_date: string | null
  po_number: string | null
  items: {
    name: string
    qty: string
    unit: string | null
    unit_price_paise: number
    tax_rate: string
    amount_paise: number | null
  }[]
  subtotal_paise: number | null
  cgst_paise: number
  sgst_paise: number
  igst_paise: number
  total_paise: number | null
  field_confidence: Record<string, number>
}

export interface Invoice {
  invoice_id: string
  status: InvoiceStatus
  status_reason: string | null
  file_name: string
  content_type: string
  file_size: number
  file_hash: string
  extracted: Extracted | null
  match_result: MatchResult | null
  validation_issues: string[]
  ai_usage: { calls: number; input_tokens: number; output_tokens: number; latency_ms: number } | null
  decision: Decision | null
  decision_reason: string | null
  decision_rule: string | null
  explanation: string | null
  explanation_source: 'agent' | 'template' | null
  resolution: Resolution | null
  supplier_email_draft: string | null
  uploaded_by: string
  approved_by: string | null
  approved_by_email: string | null
  approval_comment: string | null
  rejected_by: string | null
  rejected_by_email: string | null
  rejection_reason: string | null
  duplicate_of: string | null
  ledger_key: string | null
  posted_by: string | null
  processing_attempts: number
  created_at: string
  updated_at: string
  status_times: Record<string, string>
}

export interface Resolution {
  proposed_po: string | null
  reasoning: string | null
  fitting_pos: string[]
  verified: boolean
  message: string
}

export interface LedgerEntry {
  idempotency_key: string
  invoice_id: string
  invoice_no: string
  supplier_id: string
  supplier_name: string
  amount_paise: number
  po_number: string
  posted_by: string
  posted_at: string
}

export interface AuditEntry {
  invoice_id: string
  action: string
  actor: string
  from_status: string | null
  to_status: string | null
  details: string | null
  timestamp: string
}
