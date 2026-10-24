# Evaluation harness

Runs the 60-case test set through the real backend (FastAPI app, pipeline and Firestore emulator), checks every outcome against ground truth and writes a report to `eval/reports/` as Markdown and JSON.

## Run it

From the repo root, with the backend virtualenv active and the emulators running (`firebase emulators:start`):

```bash
pip install -r eval/requirements.txt

pytest eval --report --agents gemini     # real Gemini: the numbers to quote
pytest eval --report                     # ground-truth stand-ins, no Gemini (free, ~1 minute)
```

`--agents gemini` uses your Vertex AI setup from `backend/.env` (`EXTRACTOR=gemini`, see [docs/testing-with-gemini.md](../docs/testing-with-gemini.md)). Every invoice is read by Gemini, every exception is explained by Gemini and scored by the judge, and each of the 60 cases runs 3 times, so it makes several hundred calls.

| Option | Default | |
|---|---|---|
| `--agents gemini\|oracle` | `oracle` | `gemini` calls the real Extraction, Resolution and Explanation agents. `oracle` replaces them with stand-ins that return the ground truth, which tests everything after reading (validation, matching, decisions, approval, posting, end state) |
| `--split dev\|holdout\|all` | `all` | Tune on `dev` (42 cases); keep `holdout` (18 cases) for checking you haven't tuned to the test set |
| `--runs N` | 3 | Runs per case; decisions are compared across runs for consistency |
| `--report` | off | Save the report; without it you get a summary in the terminal |
| `--no-judge` | off | Skip the LLM judge of explanations |

The harness wipes the database before every case, so it refuses to run unless `FIRESTORE_EMULATOR_HOST` is set. It never touches a real Firestore.

## What a case is

`eval/cases/{dev,holdout}/<case>/` holds the invoice file (PDF, or a JPEG for scanned and photographed copies), any earlier invoice it duplicates, and `truth.json`:

- `world`: the suppliers, purchase orders and deliveries the harness creates through the API first
- `prior`: invoices uploaded before this one (the originals of duplicates), each expected to be posted
- `invoice.reading`: the correct reading, in the Extraction Agent's JSON shape (values as printed, `null` for a missing or unreadable field)
- `invoice.fields`: the same, normalised, for field-level accuracy
- `expect`: the decision and rule, final status, matched PO, correct amount, ledger entries and each PO's billing status afterwards

Invoices waiting for approval are approved by a manager when the case says one would (a small price difference, a PO found by the Resolution Agent), so the ledger is checked for those too.

| Case type | Cases | Expected |
|---|---|---|
| Perfect match | 15 | auto-approved and posted |
| Small price difference (within 2%) | 6 | manager approval, then posted at the PO price |
| Large price overcharge (3% to 50%) | 6 | hold |
| Short delivery | 6 | hold |
| Duplicate: same file (3), scanned copy, number re-formatted | 5 | block; the original is paid once |
| Missing PO number, one clear match | 4 | manager approval, then posted |
| No matching PO: unknown PO, unknown supplier, another supplier's PO, no PO fits | 4 | needs review |
| Missing invoice number, missing date, stained total | 3 | needs review |
| Blurry but legible | 3 | auto-approved and posted |
| Varied layouts with GST (0, 5, 12, 18%; CGST + SGST and IGST) | 8 | auto-approved and posted |

There are four layouts (plain grid, coloured banner, narrow counter bill, accounting-software letterhead with HSN codes and the amount in words), and 15 invoices are scan-like copies: rotated, noisy, low resolution, blurred or photocopied.

Expected decisions come from the business rules in PROJECT_CONTEXT.md, Section 8. Expected amounts are computed in `scenarios.py` with plain arithmetic, not with the backend's matching code.

To change the test set, edit `scenarios.py` (or `catalog.py` for suppliers and products) and run `python eval/generate.py`. The output is deterministic.

## The report

| Section | What it measures |
|---|---|
| Safety | Wrong invoices auto-approved, invoices posted that shouldn't be, duplicates paid, wrong amounts posted. Target 0; any of these fails the case's test |
| Decisions | Decision accuracy overall, per split and per case type; confusion matrix; correct invoices held unnecessarily |
| End state | Ledger entries and amounts, PO billing status, and the correct amount from the 3-way match |
| Extraction | Field-level accuracy (supplier, GSTIN, invoice number and date, PO number, line items, subtotal, GST, total). Gemini only |
| Explanations | Whether each explanation mentions the invoice total and, for a wrong amount, the correct amount and difference; plus an LLM-judge score (1 to 5 for accuracy, clarity, next action and the supplier email). Judge: Gemini only |
| Consistency | Same decision on every run of a case |
| Latency and cost | Upload to final status; Gemini calls, time, tokens and cost per invoice (cost at the prices in `backend/.env`). Gemini only |
| Failure injection | Gemini timeout, invalid JSON, a Firestore write error while posting (permanent and transient), the same invoice uploaded twice at once (same file and two scans), corrupted or empty PDF, a job restarted mid-pipeline. Each has an expected safe outcome and PASS or FAIL. Gemini's replies are scripted in these tests |
| Wrong decisions | Every run that got the wrong decision, with the reason the app gave |

With `--agents oracle` a wrong decision also fails the test, since the reading is perfect. With `--agents gemini` only safety failures fail a test; everything else is measured and reported.

CI runs `pytest eval --runs 1` (oracle) on every push, so a change that breaks a decision or the end state fails the build.
