# InvoiceFlow

An agent-based accounts-payable system. Staff create purchase orders and record deliveries; when a supplier invoice is uploaded in the app, an AI agent reads it, runs a 3-way match (PO, goods receipt, invoice) and routes it to auto-approve, manager approval, hold, block or review. Payments are tracked inside the app.

The full specification and build plan is in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). The backend stack follows the Coffee-Barista project (FastAPI, Google ADK, Gemini 2.5 Flash on Vertex AI, Firestore, Firebase Auth, Cloud Run).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Setup: monorepo, FastAPI and React skeletons, Firebase Auth roles, emulators, CI, Dockerfiles | Done |
| 2 to 10 | Master data, invoice intake, extraction, matching, approval, agents, dashboard, evaluation, deployment | Not started |

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
python -m scripts.seed_emulator_users      # creates staff/manager/admin demo users
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
