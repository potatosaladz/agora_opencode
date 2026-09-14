"""Generate the committed requirement traceability matrix from repository annotations."""

from __future__ import annotations

import argparse
import sys

from traceability import MATRIX_PATH, ROOT, TraceabilityError, generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--write", action="store_true", help="write project/TRACEABILITY.csv"
    )
    action.add_argument(
        "--check", action="store_true", help="fail if the committed CSV has drifted"
    )
    args = parser.parse_args(argv)
    try:
        generated = generate(ROOT)
    except TraceabilityError as exc:
        print(f"trace-generate: {exc}", file=sys.stderr)
        return 1

    matrix = ROOT / MATRIX_PATH
    if args.write:
        matrix.write_bytes(generated.csv_bytes)
        print(
            f"trace-generate: wrote {len(generated.rows)} rows to {MATRIX_PATH.as_posix()}"
        )
        return 0
    if args.check:
        try:
            committed = matrix.read_bytes()
        except OSError as exc:
            print(
                f"trace-generate: cannot read {MATRIX_PATH.as_posix()}: {exc}",
                file=sys.stderr,
            )
            return 1
        if committed != generated.csv_bytes:
            print(
                "trace-generate: project/TRACEABILITY.csv has drifted; "
                "run python scripts/generate_traceability.py --write",
                file=sys.stderr,
            )
            return 1
        print(f"trace-generate: {len(generated.rows)} generated rows have no drift")
        return 0
    sys.stdout.buffer.write(generated.csv_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
