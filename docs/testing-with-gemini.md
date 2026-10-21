# Test the Extraction Agent with real Gemini (VS Code, your machine)

This uses your own Google Cloud service account to call Gemini on Vertex AI. Logins and data still run on the local Firebase emulators, so nothing touches a real Firestore.

## 1. One-time Google Cloud setup

In the Google Cloud console for your project:

1. Turn on the **Vertex AI API** (APIs & Services > Library > Vertex AI API > Enable).
2. Give your service account the **Vertex AI User** role (IAM & Admin > IAM).
3. Download a JSON key for it and keep it **outside** the repo, for example `C:\keys\invoiceflow-key.json` or `~/keys/invoiceflow-key.json`.

## 2. Open the project in VS Code

```bash
git clone https://github.com/tejas-sangale04/Invoice-to-payment-agent.git
cd Invoice-to-payment-agent
git checkout claude/project-thread-rs6j62     # until PR #2 is merged into main
code .
```

Install the Python extension. Then, in the VS Code terminal:

```bash
cd backend
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # Windows: copy .env.example .env
```

Pick the interpreter with Ctrl+Shift+P > "Python: Select Interpreter" > `backend/.venv`.

## 3. Put your credentials in `backend/.env`

Change these lines (the file is git-ignored):

```ini
GOOGLE_CLOUD_PROJECT=your-project-id
FIREBASE_PROJECT_ID=demo-invoiceflow
GOOGLE_CLOUD_LOCATION=asia-south1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_APPLICATION_CREDENTIALS=C:/keys/invoiceflow-key.json
EXTRACTOR=gemini
```

- `GOOGLE_CLOUD_PROJECT` is your real project. Gemini is billed there.
- `FIREBASE_PROJECT_ID` stays `demo-invoiceflow` so the app keeps using the local emulators.
- On Windows, write the key path with forward slashes.
- If you'd rather not use a key file, run `gcloud auth application-default login` and leave `GOOGLE_APPLICATION_CREDENTIALS` out.

## 4. Quick check: read one invoice (no emulators needed)

```bash
python -m scripts.try_extraction samples/sample-invoice.pdf
```

Or in VS Code: Run and Debug (Ctrl+Shift+D) > **Try extraction on sample invoice** > F5.

You should see the model, the tokens used, what Gemini read (supplier, invoice number, three lines, CGST/SGST 305.00, total 9,310.00) and **All checks passed**. Try your own invoices the same way: `python -m scripts.try_extraction path/to/invoice.pdf` (PDF, PNG or JPEG).

If checks fail, the script shows which ones, sends them back to Gemini once and prints the second reading, exactly like the app does.

## 5. Full app: upload in the browser

You need Node 22, Java 21 and `npm install -g firebase-tools`. Use three terminals:

```bash
# Terminal 1, repo root: emulators
firebase emulators:start

# Terminal 2, backend/ (venv active)
python -m scripts.seed_emulator
uvicorn app.main:app --reload --port 8000     # or Run and Debug > "Backend API"

# Terminal 3, frontend/
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:5173, sign in as `staff@invoiceflow.test` / `password123`, go to **Upload invoice** and upload `backend/samples/sample-invoice.pdf`. The invoice page shows the status moving from received to extracting. When Gemini is done it shows what was read, the confidence for each field and the tokens used.

It then stops at **Needs review** with the note "Read and checked. Matching against purchase orders and deliveries is not available yet". That's expected: the 3-way match against the purchase order isn't built yet.

## If something goes wrong

| Error | Fix |
|---|---|
| `EXTRACTOR=disabled` | Set `EXTRACTOR=gemini` in `backend/.env` |
| `DefaultCredentialsError` / could not find credentials | Check the `GOOGLE_APPLICATION_CREDENTIALS` path is absolute and the file exists |
| `403 PERMISSION_DENIED` | Enable the Vertex AI API and give the service account Vertex AI User |
| `404 NOT_FOUND` for the model | Gemini 2.5 Flash may not be offered in that region for your project; set `GOOGLE_CLOUD_LOCATION=us-central1` |
| Sign-in fails in the app | `FIREBASE_PROJECT_ID` must be `demo-invoiceflow` and the emulators must be running |
| Gemini did not answer within 60s | Raise `GEMINI_TIMEOUT_SECONDS` in `.env` |
