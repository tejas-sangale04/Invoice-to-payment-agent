"""Stand-ins for the Gemini agents that give the ground-truth answer, for `--agents oracle`.

With them the harness checks everything after reading: validation, matching, the decision
rules, approval, posting and the end state, with no Google Cloud credentials. They measure
nothing about Gemini, so the report leaves extraction accuracy, the LLM judge and AI cost out.
"""

import hashlib
import json

from app.agents.extraction import ExtractionCall, parse_output
from app.agents.resolution import LlmResolution, ResolutionCall


class OracleExtractor:
    """Returns the correct reading of each test-set file, looked up by its hash."""

    def __init__(self, readings: dict[str, dict]) -> None:
        self.readings = readings

    def extract(self, data: bytes, mime_type: str, feedback: str | None = None) -> ExtractionCall:
        reading = self.readings.get(hashlib.sha256(data).hexdigest())
        if reading is None:
            return ExtractionCall(None, "This file is not in the test set")
        parsed, error = parse_output(json.dumps(reading))
        return ExtractionCall(parsed, error)


class OracleResolver:
    """Answers with the PO the case's invoice really belongs to (or null when none does),
    after searching like the agent would, so the search tool runs too."""

    def __init__(self) -> None:
        self.answer: str | None = None

    def resolve(self, invoice: dict, search) -> ResolutionCall:
        names = [line["name"] for line in invoice["lines"]]
        search(item_name=names[0] if names else "")
        reasoning = (
            "Ground truth: the PO this invoice was made from."
            if self.answer
            else "Ground truth: none of the supplier's open POs is for this invoice."
        )
        return ResolutionCall(LlmResolution(po_number=self.answer, reasoning=reasoning), None)
