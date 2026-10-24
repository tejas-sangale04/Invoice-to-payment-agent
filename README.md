# InvoiceFlow

An agent-based accounts-payable system. Staff create purchase orders and record deliveries; when a supplier invoice is uploaded in the app, an AI agent reads it, runs a 3-way match (PO, goods receipt, invoice) and routes it to auto-approve, manager approval, hold, block or review. Payments are tracked inside the app.

The full specification and build plan is in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). The backend stack follows the Coffee-Barista project (FastAPI, Google ADK, Gemini 2.5 Flash on Vertex AI, Firestore, Firebase Auth, Cloud Run).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Setup: monorepo, FastAPI and React skeletons, Firebase Auth roles, emulators, CI, Dockerfiles | Done |
| 2 | Master data: suppliers, purchase orders, deliveries (API, screens, tests), plus business rules | Done |
| UI | Every screen from the setup guide, Section 10, with role-based navigation | Done |
| 3 | Invoice intake: upload, file storage, invoice record, background job, status machine, audit log | Done |
| 4 | Extraction: ADK Extraction Agent on Gemini, strict schema, code validation with one corrective retry | Done |
| 5 | Matching and decisions: duplicate check, supplier and PO lookup, 3-way match with partial deliveries and GST, decision rules | Done |
| 6 | Approval and posting: approval queue, separation of duties, one-time ledger posting, PO billing | Done |
| 7 | Agentic exceptions: Resolution Agent for missing PO numbers, Explanation Agent with number check and template fallback | Done |
| 8 | Dashboard and observability: metrics, JSON logs with invoice id and step, trace spans, per-step timing, AI cost | Done |
| 9 | Evaluation: 60-case test set with 4 layouts and scan-like copies, harness, report, failure-injection tests | Done |
| 10 | Deployment and docs | Not started |

Every screen is now live. `frontend/src/lib/features.ts` still holds a flag per screen.

## What works today

- Admins add suppliers (duplicate names such as "Sharma Dairy" vs "Sharma Dairy Pvt Ltd" are rejected).
- Staff create purchase orders with several lines, GST per line and a live total; IDs are sequential (PO-1, PO-2...).
- Staff record full or partial deliveries. Received quantities add up per line, and a delivery that would take a line past what was ordered is refused.
- Admins edit the business rules (price tolerance, auto-approve limit, minimum extraction confidence).
- Money is stored as integer paise, quantities and tax rates as exact decimals.
- Staff upload invoice PDFs or images. The file type is checked from its bytes (not the browser's claim), the file is stored, the invoice is created as `received` and the upload returns at once. A background job then moves it through the pipeline; the screens update live.
- Every status change and its audit entry are written in one Firestore transaction. Illegal moves (for example `matched` straight to `posted`) are refused, repeated moves are no-ops, and the pipeline resumes from the saved status after a restart.
- Errors are retried; after the last attempt the invoice ends in `failed` for a person to check, never in silent failure. Managers can reprocess invoices that are on hold, need review or failed.
- Invoice files are only reachable through short-lived signed links.
- The Extraction Agent (Google ADK, Gemini 2.5 Flash on Vertex AI, temperature 0) reads each invoice into a strict schema, copying values as printed with a confidence per field. It never calculates. Output that doesn't match the schema is never used.
- Code then converts amounts to paise and checks them: required fields, quantity x price = line amount, line amounts = subtotal, CGST = SGST or IGST alone, GST = taxable value x rate, subtotal + GST = total (each within Rs 1), and every field's confidence against the admin's minimum. If anything fails, the problems are sent back to Gemini once; if the second reading still fails, the invoice goes to a person with the reasons listed. Gemini timeouts and errors are retried by the background task.
- Tokens, calls and latency are recorded on each invoice for the Phase 8 dashboard.
- Duplicates are blocked: the same file is caught before any model call, and the same supplier + invoice number (ignoring spaces and punctuation) after reading. A rejected invoice doesn't block a corrected copy. The same supplier and total within 7 days under a new number is flagged for a manager.
- The supplier is found by GSTIN, then by name ("Sharma Dairy Pvt. Ltd." = "Sharma Dairy"). An unknown supplier, a GSTIN that belongs to someone else, or a PO for another supplier goes to review.
- The PO number is read loosely ("po-1", "P.O. No. 001" and "1" are all PO-1). Each billed line is paired with its PO line by name ("Milk" = "Full cream milk") and compared per line: billed quantity against received minus already billed (several deliveries add up; invoices approved but not yet posted count as billed, so two invoices can't bill the same delivery), price against the PO price, and GST rate against the PO rate. Code works out the correct amount and the difference.
- Code then decides, first rule wins: duplicate → block; can't match supplier, PO, a line or a unit → needs review; billed more than received → hold; price over the tolerance or GST rate differs → hold; price over but within tolerance → manager approval; total over the auto-approve limit → manager approval; possible duplicate → manager approval; otherwise auto-approve. Only overcharges count: a lower price is paid as billed. Every rule has unit tests.
- Auto-approved invoices are posted to the ledger straight away. Invoices sent for approval wait in the manager's approval queue, which shows the billed amount, the correct amount and the difference. Approving posts the invoice; rejecting needs a reason. Nobody can approve or reject an invoice they uploaded.
- Invoices without a PO number go to the Resolution Agent (ADK, Gemini), which searches the supplier's open POs with a tool and proposes one. Code then checks it: every line must be on the PO in the same unit with enough left to bill (a PO whose deliveries cover the invoice beats one that was only ordered), and it must be the only PO that fits. Otherwise the invoice goes to a person. An invoice matched this way always needs a manager.
- Every invoice that isn't auto-approved gets a plain-language explanation and, when the supplier needs to act (an overcharge, a wrong GST rate, a duplicate, a missing PO number), a draft email. The Explanation Agent writes them from facts code prepares; code then checks that the key amounts (invoice total, correct amount, difference) appear and that no other amount does. A failed check goes back to the agent once, then a template is used. Explanations never decide anything.
- With `EXCEPTION_AGENTS=disabled` (or `EXTRACTOR=disabled`) the template is used and invoices without a PO number go to a person.
- The manager dashboard (`GET /dashboard/metrics`) is worked out from the stored invoices and ledger: invoices processed, the decision breakdown, amount posted, overcharges caught (on held invoices, and the part above the PO price on invoices paid at the PO price), duplicates blocked, average time from upload to decision and per pipeline step, retries, and model calls, tokens and Gemini time per invoice. AI cost is the recorded tokens at the prices in `GEMINI_INPUT_USD_PER_MTOK`, `GEMINI_OUTPUT_USD_PER_MTOK` and `USD_TO_INR` (defaults: Gemini 2.5 Flash list prices and Rs 88 per $); change them to your own.
- Every log line from the pipeline is JSON with the `invoice_id` and `step`, including lines from the agents. Each pipeline step runs in an OpenTelemetry span (`pipeline.extract` and so on), which is a no-op until an exporter such as Cloud Trace is set up in Phase 10.
- The evaluation harness (`eval/`) runs 60 generated invoices (dev and held-out splits) through the real app and reports decision accuracy, a confusion matrix, wrong approvals, duplicates paid, ledger and PO end state, extraction accuracy per field, explanation checks with an LLM judge, consistency over 3 runs, latency and cost, plus 8 failure-injection tests. See [eval/README.md](eval/README.md).
- Posting is one Firestore transaction: it creates `ledger_entries/{supplier_id}_{invoice_no}`, adds the billed quantities to the PO (open → partially billed → fully billed) and moves the invoice to `posted`. If that key is already in the ledger nothing is posted, so an invoice is paid once even if two copies are approved at the same moment (there is an emulator test for that). The amount posted is the correct amount, at no more than the PO price.

## Background processing and file storage

| Setting | Local default | Production |
|---|---|---|
| `STORAGE_MODE` | `local` (files in `backend/.data/uploads`) | `gcs` with `GCS_BUCKET`; links are V4 signed URLs signed through IAM, so the Cloud Run service account needs Service Account Token Creator on itself |
| `TASKS_MODE` | `inline` (runs in the API process after the upload response, same retry logic) | `cloud_tasks` with `TASKS_QUEUE`, `TASKS_LOCATION`, `TASKS_SERVICE_ACCOUNT` and `API_BASE_URL` |
| `MAX_PROCESSING_ATTEMPTS` | 5 | Must match the Cloud Tasks queue's max attempts |
| `EXTRACTOR` | `disabled` in `.env.example` (no Google Cloud credentials needed; invoices go to review) | `gemini` (the default), with `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`; the service account needs Vertex AI User |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Same, or another Gemini model |

`POST /tasks/process-invoice` only accepts a Google-signed OIDC token for `TASKS_SERVICE_ACCOUNT` with the API URL as audience, and refuses every call in inline mode.

## Layout

```
backend/    FastAPI app (app/api, app/agents, app/pipeline, app/models, app/services, app/core), pytest
frontend/   React + Vite + TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, React Router, Firebase Auth
eval/       Evaluation: case generator, 60 cases (dev/holdout), harness, reports
firebase.json   Local Firebase Auth and Firestore emulators
```

## Run locally

Prerequisites: Python 3.11+, Node 24 LTS (24.12 or newer; the Firebase SDK requires it), Java 21 (for the Firestore emulator) and `npm install -g firebase-tools`.

```bash
# 1. Emulators (Auth on :9099, Firestore on :8080, UI on :4000)
firebase emulators:start

# 2. Backend (new terminal)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m scripts.seed_emulator            # demo users for each role + demo suppliers
uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev                                # http://localhost:5173
```

To try the Extraction Agent with real Gemini using your own Google Cloud service account, follow [docs/testing-with-gemini.md](docs/testing-with-gemini.md).

Demo users (emulator only), all with password `password123`: `staff@invoiceflow.test`, `manager@invoiceflow.test`, `admin@invoiceflow.test`.

## Fixing mistakes

A manager can delete an invoice that was never posted (needs review, failed, on hold, waiting, rejected or blocked), so a corrected copy can be uploaded; the audit log keeps its history and records the deletion. A manager can also edit a PO's lines until an invoice has been posted against it; received goods can't be removed or reduced below what arrived. Posted invoices and the POs they billed are locked. For an invoice stuck because its PO was wrong, fix the PO and press Reprocess instead of deleting.

## Held invoices

An invoice on hold (billed more than was delivered, or priced above the limit) also appears in the approval queue. A manager can approve it with a comment: it is posted at the correct amount (what was delivered, at the PO price), not the billed amount, only that quantity counts as billed on the PO, and no email goes to the supplier. Rejecting it can email the supplier as usual. Another manager has to decide, as for any invoice.

## Emailing suppliers

A manager can email the supplier on file for an invoice, most often when rejecting it. The Explanation Agent writes the email (a template if Gemini is off or its text fails the amount check), the manager reads and edits it, and only then is it sent. The recipient is always the invoice's supplier, never an address typed into a request. Email is off until you set `EMAIL_MODE=smtp` and the SMTP settings in `backend/.env`; `backend/.env.example` has a Brevo example (SMTP login and key, and `EMAIL_FROM` must be a verified sender). A failed send is recorded on the invoice and can be sent again; it does not undo the rejection.

## Roles and auth

Roles (`staff`, `manager`, `admin`) are Firebase custom claims. Every backend endpoint verifies the Firebase ID token and reads the role from its claims, never from the request body. Each role includes everything the role below it can do. Admins assign roles with `PUT /users/{uid}/role`; the user picks up the new role on their next sign-in.

All errors have the same shape: `{"error": {"code": "...", "message": "...", "details": ...}}`.

## Tests

```bash
cd backend && pytest -m "not emulator"                                     # unit tests
firebase emulators:exec --only auth,firestore "cd backend && pytest -m emulator"   # from repo root
cd frontend && npm run lint && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above, the evaluation with ground-truth stand-ins (`pytest eval --runs 1`), and both Docker builds.

## Evaluation

```bash
pip install -r eval/requirements.txt          # from the repo root, backend venv active
pytest eval --report --agents gemini          # real Gemini (needs EXTRACTOR=gemini in backend/.env)
pytest eval --report                          # no Gemini: checks everything after reading
```

Needs the emulators running; the report lands in `eval/reports/`. Accuracy, latency and cost figures come only from a `--agents gemini` run. Details in [eval/README.md](eval/README.md).

## Deploy

`backend/Dockerfile` and `frontend/Dockerfile` build separate Cloud Run services (both listen on `$PORT`, default 8080). Frontend Firebase config is passed as `VITE_*` build args. Cloud Run deployment scripts come in Phase 10.
