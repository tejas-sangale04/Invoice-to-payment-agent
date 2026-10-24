"""Writes the evaluation test set to eval/cases/{dev,holdout}/<case>/: the invoice files (PDF,
or JPEG for scan-like copies) and truth.json with the expected reading, decision and end state.

    python eval/generate.py

The output is deterministic, so regenerating gives the same files and the same file hashes.
"""

import json
import shutil
import sys
from pathlib import Path

from layouts import make_messy, render_pdf
from scenarios import KINDS, Doc, build_cases, printed, totals, truth

CASES_DIR = Path(__file__).parent / "cases"
AUTO_APPROVE_LIMIT_PAISE = 5_000_000  # the default business rule


def document(doc: Doc, seed: int) -> tuple[bytes, str]:
    pdf = render_pdf(printed(doc), doc.layout, doc.smudged, seed)
    return (make_messy(pdf, doc.messy, seed), "jpg") if doc.messy else (pdf, "pdf")


def main() -> None:
    cases = build_cases()
    problems = []
    for case in cases:
        numbers = [d.invoice_no for d in [*case.prior, case.invoice]]
        if case.kind != "duplicate" and len(set(numbers)) != len(numbers):
            problems.append(f"{case.id}: invoice numbers repeat")
        if totals(case.invoice)["total"] > AUTO_APPROVE_LIMIT_PAISE:
            problems.append(f"{case.id}: total is above the auto-approve limit")
    if problems:
        sys.exit("\n".join(problems))

    if CASES_DIR.exists():
        shutil.rmtree(CASES_DIR)
    for seed, case in enumerate(cases):
        folder = CASES_DIR / case.split / case.id
        folder.mkdir(parents=True)
        files: dict[str, str] = {}
        prior_bytes = None
        for n, doc in enumerate(case.prior, 1):
            data, ext = document(doc, seed * 10 + n)
            files[f"prior-{n}"] = f"prior-{n}.{ext}"
            (folder / files[f"prior-{n}"]).write_bytes(data)
            prior_bytes = prior_bytes or (data, ext)
        if case.same_file:
            data, ext = prior_bytes
        else:
            data, ext = document(case.invoice, seed * 10)
        files["invoice"] = f"invoice.{ext}"
        (folder / files["invoice"]).write_bytes(data)
        (folder / "truth.json").write_text(
            json.dumps(truth(case, files), indent=2, ensure_ascii=False) + "\n"
        )

    by_kind = {k: [c for c in cases if c.kind == k] for k in KINDS}
    for kind, label in KINDS.items():
        dev = sum(c.split == "dev" for c in by_kind[kind])
        print(
            f"{label:<45} {len(by_kind[kind]):>3}  (dev {dev}, holdout {len(by_kind[kind]) - dev})"
        )
    dev = sum(c.split == "dev" for c in cases)
    print(f"{'Total':<45} {len(cases):>3}  (dev {dev}, holdout {len(cases) - dev})")
    print(f"Written to {CASES_DIR}")


if __name__ == "__main__":
    main()
