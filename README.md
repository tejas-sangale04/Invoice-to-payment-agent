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
| 5 to 10 | Matching, approval, agents, dashboard, evaluation, deployment | Not started |

Until Phase 5 adds the 3-way match, invoices that read and check out are routed to `needs_review` with a clear reason, never approved. Screens whose backend is not built yet (approval queue, ledger, dashboard) show a notice naming the phase that switches them on and make no API calls. Each is turned on by one flag in `frontend/src/lib/features.ts`.

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

## Roles and auth

Roles (`staff`, `manager`, `admin`) are Firebase custom claims. Every backend endpoint verifies the Firebase ID token and reads the role from its claims, never from the request body. Each role includes everything the role below it can do. Admins assign roles with `PUT /users/{uid}/role`; the user picks up the new role on their next sign-in.

All errors have the same shape: `{"error": {"code": "...", "message": "...", "details": ...}}`.

## Tests

```bash
cd backend && pytest -m "not emulator"                                     # unit tests
firebase emulators:exec --only auth,firestore "cd backend && pytest -m emulator"   # from repo root
cd frontend && npm run lint && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above plus both Docker builds.

## Deploy

`backend/Dockerfile` and `frontend/Dockerfile` build separate Cloud Run services (both listen on `$PORT`, default 8080). Frontend Firebase config is passed as `VITE_*` build args. Cloud Run deployment scripts come in Phase 10.
