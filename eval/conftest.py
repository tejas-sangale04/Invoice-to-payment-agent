"""pytest setup for the evaluation: command-line options, the backend app wired to the Firestore
emulator, and the report written at the end of the session.

    pytest eval --report                      # whole test set, 3 runs per case
    pytest eval --report --split dev --runs 1
"""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parent
CASES = EVAL / "cases"
REPORTS = EVAL / "reports"
sys.path.insert(0, str(EVAL.parent / "backend"))
# Invoices are processed in this process, synchronously, and files kept on local disk.
os.environ["TASKS_MODE"] = "inline"
os.environ["STORAGE_MODE"] = "local"

# Everything the session collects for the report.
RESULTS: dict[str, list] = {"cases": [], "failures": []}


def pytest_addoption(parser: pytest.Parser) -> None:
    g = parser.getgroup("invoiceflow evaluation")
    g.addoption("--report", action="store_true", help="save the report in eval/reports/")
    g.addoption(
        "--agents",
        choices=["gemini", "oracle"],
        default="oracle",
        help="gemini: the real agents (needs Vertex AI credentials in backend/.env); oracle "
        "(default): ground-truth stand-ins, no Gemini calls.",
    )
    g.addoption("--split", choices=["dev", "holdout", "all"], default="all")
    g.addoption("--runs", type=int, default=3, help="runs per case, for consistency (default 3)")
    g.addoption("--no-judge", action="store_true", help="skip the LLM judge of explanations")


def pytest_configure(config: pytest.Config) -> None:
    from app.core.config import get_settings  # loads backend/.env

    get_settings.cache_clear()
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        raise pytest.UsageError(
            "The evaluation wipes the database before every case, so it only runs against the "
            "Firestore emulator. Start it (firebase emulators:start) and set "
            "FIRESTORE_EMULATOR_HOST, as in backend/.env.example."
        )
    s = get_settings()
    agents = config.getoption("--agents")
    if agents == "gemini" and not (s.extractor == "gemini" and s.agents_enabled):
        raise pytest.UsageError(
            "--agents gemini needs EXTRACTOR=gemini (and EXCEPTION_AGENTS unset or gemini) and "
            "Vertex AI credentials in backend/.env; see docs/testing-with-gemini.md."
        )
    if config.getoption("--runs") < 1:
        raise pytest.UsageError("--runs must be at least 1")
    config.eval_agents = agents
    config.eval_started = datetime.now().astimezone().isoformat(timespec="seconds")


def case_dirs(split: str) -> list[Path]:
    splits = ["dev", "holdout"] if split == "all" else [split]
    return [d for s in splits for d in sorted((CASES / s).iterdir()) if d.is_dir()]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "case_dir" in metafunc.fixturenames:
        dirs = case_dirs(metafunc.config.getoption("--split"))
        metafunc.parametrize("case_dir", dirs, ids=[d.name for d in dirs])


@dataclass
class Evaluation:
    api: object
    agents: str
    runs: int
    prices: dict
    resolver: object = None
    judge: object = None
    results: dict = field(default_factory=lambda: RESULTS)

    def prepare(self, truth: dict) -> None:
        if self.resolver is not None:
            self.resolver.answer = truth["expect"]["po_number"]


def _readings() -> dict[str, dict]:
    out = {}
    for t in CASES.glob("*/*/truth.json"):
        truth = json.loads(t.read_text())
        docs = [(p["file"], p["reading"]) for p in truth["prior"]]
        if not truth["invoice"]["same_file_as_prior"]:
            docs.append((truth["invoice"]["file"], truth["invoice"]["reading"]))
        for name, reading in docs:
            out[hashlib.sha256((t.parent / name).read_bytes()).hexdigest()] = reading
    return out


@pytest.fixture(scope="session")
def evaluation(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory):
    import harness
    from app.agents import explanation, extraction, resolution
    from app.core.config import get_settings
    from app.services import firebase
    from app.services import storage as storage_svc

    config = request.config
    s = get_settings()
    mp = pytest.MonkeyPatch()
    mp.setattr(firebase, "verify_id_token", harness.verify_token)
    api, store = harness.make_client(tmp_path_factory.mktemp("uploads"))
    mp.setattr(storage_svc, "get_storage", lambda: store)
    ev = Evaluation(
        api,
        config.eval_agents,
        config.getoption("--runs"),
        {
            "input_usd_per_mtok": s.gemini_input_usd_per_mtok,
            "output_usd_per_mtok": s.gemini_output_usd_per_mtok,
            "usd_to_inr": s.usd_to_inr,
        },
    )
    if ev.agents == "oracle":
        from oracle import OracleExtractor, OracleResolver

        reader, ev.resolver = OracleExtractor(_readings()), OracleResolver()
        mp.setattr(extraction, "get_extractor", lambda: reader)
        mp.setattr(explanation, "get_explainer", lambda: None)
        mp.setattr(resolution, "get_resolver", lambda: ev.resolver)
    elif not config.getoption("--no-judge"):
        from judge import Judge

        ev.judge = Judge()
    yield ev
    mp.undo()


def _git() -> str:
    def run(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=EVAL).stdout

    commit = run("rev-parse", "--short", "HEAD").strip() or "unknown"
    return commit + (" with local changes" if run("status", "--porcelain").strip() else "")


def _summary(config: pytest.Config) -> dict | None:
    if not (RESULTS["cases"] or RESULTS["failures"]):
        return None
    from app.core.config import get_settings
    from app.models.rules import BusinessRules
    from report import summarize

    s = get_settings()
    meta = {
        "started_at": config.eval_started,
        "agents": config.eval_agents,
        "model": s.gemini_model,
        "split": config.getoption("--split"),
        "runs_per_case": config.getoption("--runs"),
        "rules": BusinessRules().model_dump(mode="json"),
        "prices": f"${s.gemini_input_usd_per_mtok}/${s.gemini_output_usd_per_mtok} per million "
        f"input/output tokens, Rs {s.usd_to_inr}/$",
        "git": _git(),
    }
    return summarize(meta, RESULTS["cases"], RESULTS["failures"])


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    summary = _summary(config)
    if summary is None:
        return
    tr = terminalreporter
    tr.section("InvoiceFlow evaluation")
    sf = summary["safety"]
    da = summary["decision_accuracy"]
    tr.write_line(f"agents: {config.eval_agents}, {summary['cases']} cases, {summary['runs']} runs")
    if da["runs"]:
        tr.write_line(f"decision accuracy: {da['correct']}/{da['runs']}")
    tr.write_line(
        f"wrong approvals: {len(sf['wrong_approvals'])}, duplicates paid: "
        f"{len(sf['duplicates_paid'])}, wrong amounts posted: {len(sf['wrong_amounts'])}"
    )
    fi = summary["failure_injection"]
    if fi:
        tr.write_line(f"failure injection: {sum(f['passed'] for f in fi)}/{len(fi)} passed")
    if config.getoption("--report"):
        from report import save

        path = save(summary, RESULTS["cases"], REPORTS)
        tr.write_line(f"report: {path} (and .json)")
