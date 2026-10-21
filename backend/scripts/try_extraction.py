"""Read one invoice file with the real Extraction Agent and print what it found.

Needs Google Cloud credentials for Vertex AI, nothing else (no emulators, no frontend):

    python -m scripts.try_extraction samples/sample-invoice.pdf

It runs the same steps as the pipeline: Gemini reads the file, code converts and checks the
reading, and if checks fail the problems go back to Gemini once.
"""

import json
import os
import sys
from pathlib import Path

from app.agents import extraction
from app.core.config import get_settings
from app.models.rules import BusinessRules
from app.pipeline.runner import MAX_EXTRACTION_ATTEMPTS
from app.pipeline.validate import check, to_extracted
from app.services.files import InvalidFile, sniff


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m scripts.try_extraction <invoice.pdf|png|jpg>")
    path = Path(sys.argv[1])
    if not path.is_file():
        sys.exit(f"No such file: {path}")
    try:
        content_type, _ = sniff(path.read_bytes())
    except InvalidFile as exc:
        sys.exit(str(exc))

    s = get_settings()
    if s.extractor == "disabled":
        sys.exit("EXTRACTOR=disabled in backend/.env. Set EXTRACTOR=gemini to call Gemini.")
    print(
        f"Model {s.gemini_model} | project {os.environ.get('GOOGLE_CLOUD_PROJECT')} | "
        f"location {os.environ.get('GOOGLE_CLOUD_LOCATION')}\n"
    )

    extractor = extraction.get_extractor()
    min_confidence = BusinessRules().min_field_confidence
    feedback: str | None = None
    for attempt in range(1, MAX_EXTRACTION_ATTEMPTS + 1):
        call = extractor.extract(path.read_bytes(), content_type, feedback)
        print(
            f"Attempt {attempt}: {call.latency_ms} ms, "
            f"{call.input_tokens} input / {call.output_tokens} output tokens"
        )
        if call.parsed is None:
            issues = [call.error or "The response could not be read"]
        else:
            print(json.dumps(call.parsed.model_dump(), indent=2, ensure_ascii=False))
            extracted, issues = to_extracted(call.parsed)
            issues += check(extracted, min_confidence)
        if not issues:
            print("\nAll checks passed. In the app this invoice would move on to validated.")
            return
        print("\nChecks that failed:\n" + "\n".join(f"- {i}" for i in issues) + "\n")
        feedback = "\n".join(f"- {i}" for i in issues)
    print("Still failing after the retry. In the app this invoice would go to needs_review.")


if __name__ == "__main__":
    main()
