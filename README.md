# InvoiceFlow

An agent-based accounts-payable system. Staff create purchase orders and record deliveries; when a supplier invoice is uploaded in the app, an AI agent reads it, runs a 3-way match (PO, goods receipt, invoice) and routes it to auto-approve, manager approval, hold, block or review. Payments are tracked inside the app.

The full specification and build plan is in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). The backend stack follows the Coffee-Barista project (FastAPI, Google ADK, Gemini 2.5 Flash on Vertex AI, Firestore, Firebase Auth, Cloud Run).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Setup: monorepo, FastAPI and React skeletons, Firebase Auth roles, emulators, CI, Dockerfiles | Done |
| 2 | Master data: suppliers, purchase orders, deliveries (API, screens, tests), plus business rules | Done |
| UI | Every screen from the setup guide, Section 10, with role-based navigation | Done |
| 3 to 10 | Invoice intake, extraction, matching, approval, agents, dashboard, evaluation, deployment | Not started |

Screens whose backend is not built yet (upload, invoices, approval queue, ledger, dashboard) show a notice naming the phase that switches them on and make no API calls. Each is turned on by one flag in `frontend/src/lib/features.ts`.

## What works today

- Admins add suppliers (duplicate names such as "Sharma Dairy" vs "Sharma Dairy Pvt Ltd" are rejected).
- Staff create purchase orders with several lines, GST per line and a live total; IDs are sequential (PO-1, PO-2...).
- Staff record full or partial deliveries. Received quantities add up per line, and a delivery that would take a line past what was ordered is refused.
- Admins edit the business rules (price tolerance, auto-approve limit, minimum extraction confidence).
- Money is stored as integer paise, quantities and tax rates as exact decimals.

## Layout

```
backend/    FastAPI app (app/api, app/agents, app/pipeline, app/models, app/services, app/core), pytest
frontend/   React + Vite + TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, React Router, Firebase Auth
firebase.json   Local Firebase Auth and Firestore emulators
```

## Run locally

Prerequisites: Python 3.11+, Node 22, Java 21 (for the Firestore emulator) and `npm install -g firebase-tools`.

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
