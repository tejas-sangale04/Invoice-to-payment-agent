# Build Prompt: InvoiceFlow — AI Invoice-to-Payment (Procure-to-Pay) Agent

> Paste this whole file into your AI coding assistant, or save it in the repo root as `PROJECT_CONTEXT.md`. "InvoiceFlow" is a working name; rename it freely.

---

## 1. Your role

You are a senior full-stack and AI engineer helping me build an industry-ready, agent-based accounts-payable system. Build it **phase by phase** (Section 13). After each phase, stop and give me:
- a summary of what was built
- how to run and test it
- any decisions or assumptions you made

Don't start the next phase until I confirm.

Rules for you:
- Ask me before making any major assumption that isn't covered here.
- Write clean, typed, tested code. No placeholder logic left as "TODO" without telling me.
- Never hardcode secrets or keys.
- **Never invent accuracy, latency or cost numbers.** Every metric must come from the evaluation harness actually being run.

---

## 2. Project overview

Companies must check supplier invoices before paying them. The standard check is a **3-way match**:

| Document | Meaning | Created by |
|---|---|---|
| Purchase Order (PO) | What we ordered (item, quantity, agreed price) | Staff, before buying |
| Goods Receipt (GR) | What actually arrived | Staff, when delivery arrives |
| Invoice | What the supplier is charging | Supplier (PDF) |

InvoiceFlow lets staff create POs and record deliveries. When a supplier invoice PDF is uploaded, an AI agent:
1. checks for duplicates
2. reads the PDF with Gemini
3. validates the extracted data with code
4. finds the matching PO and receipts
5. runs a 3-way match with deterministic rules
6. decides: auto-approve, manager approval, hold, block or needs review
7. explains problems in plain language and drafts a supplier email
8. posts approved invoices to a ledger exactly once
9. logs every step in an audit trail

**Core design principle:** the LLM handles messy reading and language. **Code handles all math, matching and decisions.** Humans approve anything risky. When unsure, the system routes to a human instead of guessing.

**Example:** PO-205 orders 50 L milk at ₹60. Only 40 L are received. The invoice bills 50 L (₹3,000). The agent detects a quantity mismatch, calculates the correct amount (₹2,400, overcharge ₹600), puts the invoice on hold, and drafts an email asking the supplier for a corrected invoice.

---

## 3. Tech stack

**Frontend**
- React + Vite + TypeScript
- Tailwind CSS + shadcn/ui
- TanStack Query (server state), React Router (pages)
- Recharts (dashboard)
- Firebase Authentication JS SDK

**Backend and AI**
- Python 3.11+, FastAPI, Pydantic v2
- Google ADK for agent orchestration
- Gemini via Vertex AI (multimodal PDF reading, explanations, emails)
- Firestore (all business data)
- Cloud Storage (invoice PDFs)
- Cloud Tasks (background processing with retries)
- Firebase Authentication with custom claims for roles
- Secret Manager (secrets)
- Cloud Logging + Cloud Trace (observability)
- pytest (unit, integration and evaluation tests)
- Firestore emulator for local development and tests

**Deployment:** frontend and backend as separate Cloud Run services. Provide Dockerfiles for both.

---

## 4. Users and roles

| Role | Can do |
|---|---|
| `staff` | Create POs, record deliveries, upload invoices, view invoices |
| `manager` | Everything staff can do, plus approve/reject invoices, view ledger and dashboard |
| `admin` | Everything, plus manage users, suppliers and business rules |

- Roles are stored as Firebase custom claims.
- The backend verifies the Firebase ID token **and** the role on every endpoint. Never trust the frontend for permissions.
- A user cannot approve an invoice they uploaded (separation of duties).

---

## 5. Data model (Firestore)

Store all money as **integer paise** (₹60.00 = 6000) to avoid floating-point errors. Use `Decimal` for any intermediate calculations.

```
suppliers/{supplier_id}
  name, normalized_name, gstin (optional), email, created_at

purchase_orders/{po_number}            e.g. PO-205
  supplier_id, status: open | partially_billed | fully_billed | closed
  items: [{ line_id, name, qty, unit, unit_price_paise, tax_rate }]
  created_by, created_at

goods_receipts/{gr_id}                 e.g. GR-310
  po_number, items: [{ line_id, qty_received }]
  received_by, received_on, notes

invoices/{invoice_id}
  file_path (Cloud Storage), file_hash (sha256)
  status (see Section 6)
  extracted: { supplier_name, invoice_no, invoice_date, po_number,
               items: [{ name, qty, unit, unit_price_paise, tax_rate }],
               subtotal_paise, cgst_paise, sgst_paise, igst_paise, total_paise,
               field_confidence: { ... } }
  match_result: { matched_po, per_line: [...], issues: [...],
                  correct_amount_paise, difference_paise }
  decision: auto_approve | manager_approval | hold | block | needs_review
  decision_reason (code-generated, structured)
  explanation (LLM-generated, plain language)
  supplier_email_draft
  uploaded_by, approved_by, timestamps for each status

ledger_entries/{idempotency_key}       key = supplier_id + "_" + invoice_no
  invoice_id, supplier_id, amount_paise, po_number, posted_by, posted_at

audit_log/{auto_id}
  invoice_id, action, actor (user id or "agent"), from_status, to_status,
  details, timestamp

business_rules/default
  price_tolerance_percent: 2.0
  auto_approve_max_paise: (e.g. 5000000 = ₹50,000)
  min_field_confidence: 0.85
```

---

## 6. Invoice status machine

```
received → extracting → extracted → validated → matched →
   ├─ auto_approved ─────────────┐
   ├─ pending_approval → approved ┴→ posted → paid (mock)
   │                  └→ rejected
   ├─ on_hold
   ├─ blocked_duplicate
   └─ needs_review
failed (after retries exhausted → treated as needs_review)
```

Rules:
- Every status change is written in a Firestore transaction **together with** its audit log entry.
- Processing is **resumable**: if a task restarts, it continues from the last saved status, not from the beginning.
- Each step is idempotent: running it twice gives the same result.

---

## 7. Agent workflow

Upload returns immediately. The backend saves the PDF to Cloud Storage, creates the invoice record (`received`), and enqueues a Cloud Tasks job. The job runs this pipeline:

| # | Step | Done by | Details |
|---|---|---|---|
| 1 | Duplicate check | Code | Block if the same `file_hash` exists, or the same supplier + invoice number exists. Flag as possible duplicate if same supplier + same total + date within 7 days, but a different invoice number |
| 2 | Extraction | **LLM (Extraction Agent)** | Gemini reads the PDF and returns JSON matching a strict Pydantic schema, plus per-field confidence |
| 3 | Validation | Code | Line items × prices = subtotal; subtotal + taxes = total; required fields present; confidence ≥ threshold. On failure: one retry with the error message fed back to Gemini, then `needs_review` |
| 4 | Find PO and receipts | Code | Look up by PO number. If no PO number, hand off to step 4b |
| 4b | Resolve missing PO | **LLM (Resolution Agent)** with tools | Uses tools to search open POs by supplier, items and date range, and proposes a match with reasoning. **Code verifies** the proposal: exactly one candidate must fit, otherwise `needs_review`. Always flagged as "matched without PO number" |
| 5 | 3-way match | Code | Per line: compare billed qty vs (total received − already billed), and billed price vs PO price. Supports partial deliveries and multiple receipts per PO. Computes correct amount and difference |
| 6 | Decide | Code | Apply rules from `business_rules` (Section 8). Store a structured reason |
| 7 | Explain | **LLM (Explanation Agent)** | For any non-auto-approved invoice: write a plain-language explanation and a supplier email draft, using only numbers from `match_result`. Code then checks the key amounts appear in the text; if not, regenerate once, else fall back to a template |
| 8 | Approve | Human (manager) | Manager approves or rejects from the approval queue |
| 9 | Post | Code | Firestore transaction: create ledger entry with idempotency key, update PO billed quantities and status. If the key already exists, do nothing |

**Use Google ADK** for the LLM agents (Extraction, Resolution, Explanation) and their tools. Deterministic steps are plain Python functions, which may also be exposed as ADK tools. **The LLM never decides whether to pay.**

---

## 8. Business rules (decision logic)

Evaluate in this order; first match wins:
1. Duplicate → `block`
2. Extraction failed or low confidence → `needs_review`
3. No matching PO found → `needs_review`
4. Billed quantity > available received quantity → `hold`
5. Price difference > `price_tolerance_percent` → `hold`
6. Price difference > 0 and ≤ tolerance → `manager_approval`
7. Total > `auto_approve_max_paise` → `manager_approval`
8. Matched without PO number → `manager_approval`
9. Everything matches → `auto_approve`

Rules are configurable by an admin and covered by unit tests for every branch.

**GST:** support CGST + SGST (intra-state) and IGST (inter-state). Validate that tax amounts match `taxable value × rate`, within ±₹1 rounding.

---

## 9. API endpoints (FastAPI)

```
POST   /suppliers                 GET /suppliers
POST   /purchase-orders           GET /purchase-orders, GET /purchase-orders/{po}
POST   /goods-receipts            GET /goods-receipts?po_number=
POST   /invoices (multipart upload)
GET    /invoices?status=          GET /invoices/{id}
GET    /invoices/{id}/file        (signed URL)
POST   /invoices/{id}/approve     (manager)
POST   /invoices/{id}/reject      (manager, reason required)
POST   /invoices/{id}/reprocess   (manager/admin)
GET    /ledger                    (manager)
GET    /audit-log?invoice_id=
GET    /dashboard/metrics         (manager)
GET/PUT /business-rules           (admin)
POST   /tasks/process-invoice     (internal, Cloud Tasks only, authenticated)
```

Use Pydantic models for all requests and responses, consistent error format, and pagination on list endpoints.

---

## 10. Frontend screens (React)

| Screen | Role | Notes |
|---|---|---|
| Login | All | Firebase Auth |
| Create purchase order | Staff+ | Supplier dropdown, multiple line items, live total |
| Record delivery | Staff+ | Pick an open PO, enter received qty per line, show already received |
| Upload invoice | Staff+ | Drag and drop PDF/image, shows status after upload |
| Invoices list | All | Filter by status, supplier, date; status badges; auto-refresh |
| Invoice detail | All | PDF preview on the left; extracted data, 3-way match table, decision, explanation and audit timeline on the right |
| Approval queue | Manager | Approve or reject with comment; shows difference amount clearly |
| Ledger | Manager | Posted entries, totals |
| Dashboard | Manager | Invoices processed, decision breakdown, money saved by holds, average processing time, average AI cost per invoice |
| Business rules | Admin | Edit tolerances and limits |

Design: clean and professional, responsive, with clear loading, empty and error states. Use green, amber and red only to mean OK, attention and problem.

---

## 11. Reliability requirements

- **Retries:** Cloud Tasks retries with backoff; Gemini calls have timeouts and limited retries.
- **No double payment:** ledger idempotency key + Firestore transactions.
- **No half-saved state:** multi-document updates happen in transactions.
- **Structured output:** Gemini output is always validated by Pydantic; invalid output is never used.
- **Safe failure:** any unexpected error ends in `needs_review` with a clear reason, never in silent failure or auto-approval.
- **Concurrency:** two simultaneous uploads of the same invoice must produce one ledger entry at most.
- **Observability:** structured JSON logs with `invoice_id` on every line; trace spans per pipeline step; record latency, tokens and retries per invoice in Firestore for the dashboard.
- **Security:** signed URLs for PDFs, role checks on every endpoint, Cloud Tasks endpoint not publicly callable, secrets in Secret Manager.

---

## 12. Evaluation harness

Create an `eval/` folder that can run with one command (for example `pytest eval/ --report`) against the Firestore emulator or a separate test database.

**1. Synthetic data generator** (`eval/generate.py`)
- Generates suppliers, POs, receipts and invoice PDFs using `reportlab`, with at least 4 different invoice layouts.
- Produces "messy" variants with Pillow: slight rotation, blur, noise, low resolution, scanned-image style.
- Writes a ground-truth JSON for each case: expected extracted fields, expected issue, correct amount and expected decision.

**2. Test set (about 60 cases), split into dev (about 40) and a held-out set (about 20)**

| Case type | Approx. count |
|---|---|
| Perfect match | 15 |
| Small price difference (within tolerance) | 6 |
| Large price overcharge | 6 |
| Short delivery | 6 |
| Duplicate (exact and near-duplicate) | 5 |
| Missing PO number, one clear match | 4 |
| No matching PO | 4 |
| Blurry or missing field | 6 |
| Varied layouts with GST | 8 |

**3. Metrics in the report**
- Field-level extraction accuracy
- Decision accuracy and confusion matrix
- **Wrong invoices approved** (target 0)
- **Duplicates paid** (target 0)
- Correct invoices held unnecessarily
- End-state checks: ledger amounts, no duplicate entries, PO status correct
- Explanation check: correct amounts mentioned (automatic) and an LLM-judge rubric score
- Consistency: each case run 3 times, same decision
- Average latency, tokens and cost per invoice

**4. Failure-injection tests**
- Gemini timeout, Gemini invalid JSON, Firestore write error during posting, same invoice uploaded twice concurrently, corrupted/empty PDF, Cloud Tasks job restarted mid-pipeline.
- Each has an expected safe outcome and a pass/fail result.

The report is saved as Markdown and JSON in `eval/reports/` with a timestamp, so results can be compared across runs.

---

## 13. Build phases

1. **Setup:** monorepo structure, FastAPI skeleton, React skeleton, Firebase Auth with roles, Firestore emulator, CI running tests, Dockerfiles.
2. **Master data:** suppliers, Create PO and Record delivery (API + screens + tests).
3. **Invoice intake:** upload, Cloud Storage, invoice record, Cloud Tasks job, status machine, audit log.
4. **Extraction:** ADK Extraction Agent with Gemini, Pydantic schema, validation step with one corrective retry.
5. **Matching and decisions:** duplicate check, PO and receipt lookup, 3-way match with partial deliveries and GST, decision rules, full unit tests.
6. **Approval and posting:** approval queue, separation of duties, idempotent ledger posting, PO billing updates.
7. **Agentic exceptions:** Resolution Agent for missing PO numbers; Explanation Agent with number check and template fallback.
8. **Dashboard and observability:** metrics, logs, traces, cost tracking.
9. **Evaluation:** data generator, test set, report, failure-injection tests.
10. **Deployment and docs:** Cloud Run deployment, README with architecture diagram, setup steps, and the latest real evaluation report.

---

## 14. Repository structure (suggested)

```
invoiceflow/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routers
│   │   ├── agents/         # ADK agents and prompts
│   │   ├── pipeline/       # duplicate, validate, match, decide, post
│   │   ├── models/         # Pydantic schemas
│   │   ├── services/       # firestore, storage, tasks, auth
│   │   └── core/           # config, logging, errors
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── src/ (pages, components, api, hooks, lib)
│   └── Dockerfile
├── eval/
│   ├── generate.py
│   ├── cases/ (dev/, holdout/)
│   ├── test_eval.py
│   └── reports/
└── README.md
```

---

## 15. Definition of done

- All screens work end to end for every role.
- Every decision rule and failure scenario has a passing test.
- The evaluation harness runs with one command and produces a report.
- The README states only results produced by that report.
- No wrong invoice is auto-approved and no duplicate is paid in the latest evaluation run, or, if any are, they're listed with the cause and the fix.