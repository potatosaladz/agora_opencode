"""Validate generated traceability metadata, references, policy gates, and CSV drift."""

from __future__ import annotations

import csv
import io
import sys

from traceability import (
    EXPECTED_COLUMNS,
    MATRIX_PATH,
    ROOT,
    TraceabilityError,
    generate,
    validate_rows,
)

PHASE_GATES = {
    "3": {
        "FR-101",
        "FR-102",
        "FR-103",
        *(f"FR-{number}" for number in range(301, 313)),
    },
    "5": {*(f"FR-{number}" for number in range(401, 408)), "FR-409"},
}


def _parse_committed(content: bytes) -> tuple[list[dict[str, str]], list[str]]:
    problems: list[str] = []
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [], ["project/TRACEABILITY.csv is not valid UTF-8"]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
        problems.append(f"unexpected columns: {reader.fieldnames}")
    rows = list(reader)
    for line_number, row in enumerate(rows, start=2):
        if None in row:
            problems.append(f"line {line_number}: too many columns")
        if any(value is None for value in row.values()):
            problems.append(f"line {line_number}: too few columns")
    return rows, problems


def main() -> int:
    problems: list[str] = []
    try:
        generated = generate(ROOT)
    except TraceabilityError as exc:
        print(f"trace-check: {exc}", file=sys.stderr)
        return 1

    matrix = ROOT / MATRIX_PATH
    try:
        committed = matrix.read_bytes()
    except OSError as exc:
        print(
            f"trace-check: cannot read {MATRIX_PATH.as_posix()}: {exc}", file=sys.stderr
        )
        return 1
    committed_rows, csv_problems = _parse_committed(committed)
    problems.extend(csv_problems)
    problems.extend(validate_rows(ROOT, generated.rows))
    if committed != generated.csv_bytes:
        problems.append(
            "project/TRACEABILITY.csv has generated-artifact drift; "
            "run python scripts/generate_traceability.py --write"
        )
    if len(committed_rows) != len(generated.rows):
        problems.append(
            f"committed matrix has {len(committed_rows)} rows; "
            f"generator produced {len(generated.rows)}"
        )

    rows_by_id = {row["req_id"]: row for row in generated.rows}
    for phase, requirement_ids in PHASE_GATES.items():
        for req_id in sorted(requirement_ids):
            row = rows_by_id.get(req_id)
            if row is None:
                problems.append(f"missing Phase {phase} requirement row {req_id}")
                continue
            if row["status"] != "implemented" or row["phase"] != phase:
                problems.append(
                    f"{req_id}: Phase {phase} gate requires implemented status"
                )
            for field in ("design_refs", "code_paths", "tests", "last_verified"):
                if not row[field]:
                    problems.append(f"{req_id}: implemented row requires {field}")

    fr408 = rows_by_id.get("FR-408")
    if fr408 is None:
        problems.append("missing Phase 5 dependency row FR-408")
    elif fr408["status"] != "implemented" or fr408["phase"] != "10":
        problems.append("FR-408 requires implemented status in Phase 10")
    elif any(
        not fr408[field]
        for field in ("design_refs", "code_paths", "tests", "last_verified")
    ):
        problems.append("FR-408 implemented row requires complete impact-analysis evidence")

    for row in generated.rows:
        if row["status"] == "implemented":
            for field in ("design_refs", "code_paths", "tests", "last_verified"):
                if not row[field]:
                    problems.append(
                        f"{row['req_id']}: implemented row requires {field}"
                    )
        elif row["status"] == "partial" and not row["design_refs"]:
            problems.append(f"{row['req_id']}: partial row requires design_refs")

    for problem in problems:
        print(f"trace-check: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"trace-check: {len(generated.rows)} generated rows, "
        f"{generated.document_annotations} documentation annotations, "
        f"{generated.source_annotations} source annotations, "
        f"{generated.test_annotations} test annotations; committed CSV has no drift"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
