"""One test per case: run it (--runs times), score it and keep the result for the report.

A case fails when money moves that shouldn't: a wrong invoice approved, a duplicate paid, a
wrong amount posted. With --agents oracle the readings are perfect, so the case must also get
exactly the expected decision, amount and end state.
"""

import json
from pathlib import Path

from harness import run_case
from scoring import safety_failures, score


def strict_failures(run: dict) -> list[str]:
    out = []
    if not run["decision_ok"]:
        out.append(f"decision {run['decision']} ({run['rule']}): {run['decision_reason']}")
    if not run["status_ok"]:
        out.append(f"ended {run['status']}")
    if not run["end_state_ok"]:
        out += run["end_state_problems"]
    if run["correct_amount_ok"] is False:
        out.append(f"correct amount computed as {run['correct_amount_paise']}")
    e = run["explanation"]
    if e and e["expected"] and not e["amounts_ok"]:
        out.append(f"explanation misses {e['missing_amounts']}: {e['text']}")
    return out


def test_case(case_dir: Path, evaluation) -> None:
    truth = json.loads((case_dir / "truth.json").read_text())
    evaluation.prepare(truth)
    runs = []
    for _ in range(evaluation.runs):
        result = score(truth, run_case(evaluation.api, case_dir, truth), evaluation.prices)
        e = result["explanation"]
        if evaluation.judge and e and e["present"]:
            result["judge"] = evaluation.judge(truth, e["text"], e["supplier_email"])
        runs.append(result)
    evaluation.results["cases"].append(
        {
            "id": truth["id"],
            "kind": truth["kind"],
            "split": truth["split"],
            "description": truth["description"],
            "expect": truth["expect"],
            "runs": runs,
        }
    )

    check = strict_failures if evaluation.agents == "oracle" else lambda r: []
    problems = [
        f"run {n}: {p}" for n, run in enumerate(runs, 1) for p in safety_failures(run) + check(run)
    ]
    assert not problems, f"{truth['description']}\n" + "\n".join(problems)
