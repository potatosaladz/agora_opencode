"""Validate authored Phase 1 contracts against backend sources without network access."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "contracts" / "openapi.yaml"
ERRORS = ROOT / "contracts" / "errors.yaml"
BACKEND_ERRORS = ROOT / "backend" / "app" / "common" / "errors.py"
ROUTES = ROOT / "backend" / "app" / "api" / "routes"
EVENT_SCHEMA = ROOT / "contracts" / "events" / "reasoning-event.json"


def main() -> int:
    openapi = OPENAPI.read_text(encoding="utf-8")
    errors = ERRORS.read_text(encoding="utf-8")
    backend_errors = BACKEND_ERRORS.read_text(encoding="utf-8")
    problems: list[str] = []

    try:
        event_schema = json.loads(EVENT_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"Reasoning event schema is missing or invalid: {type(exc).__name__}")
    else:
        expected_event_fields = {
            "event_id",
            "ledger_seq",
            "type",
            "ts",
            "session_id",
            "actor_id",
            "actor_class",
            "round",
            "payload",
            "schema_version",
            "code_version",
        }
        if set(event_schema.get("required", ())) != expected_event_fields:
            problems.append("Reasoning event schema required fields differ from the wire contract")

    authored_paths = set(re.findall(r"^  (/[^:]+):$", openapi, flags=re.MULTILINE))
    implemented_paths: set[str] = set()
    for route_file in ROUTES.glob("*.py"):
        route_source = route_file.read_text(encoding="utf-8")
        prefix_match = re.search(r'router\s*=\s*APIRouter\(prefix="([^"]+)"', route_source)
        prefix = prefix_match.group(1) if prefix_match else ""
        implemented_paths.update(
            prefix + path
            for path in re.findall(
                r'@router\.(?:get|post|put|patch|delete)\("([^"]*)"', route_source
            )
        )
    if authored_paths != implemented_paths:
        problems.append(
            f"OpenAPI paths {sorted(authored_paths)} do not match implemented paths "
            f"{sorted(implemented_paths)}"
        )

    source_codes = set(re.findall(r'^    ([A-Z][A-Z_]+) = "\1"$', backend_errors, re.MULTILINE))
    contract_codes = set(re.findall(r"^  ([A-Z][A-Z_]+): \{", errors, re.MULTILINE))
    error_schema = re.search(
        r"^    ErrorCode:\n(?P<body>.*?)(?=^    [A-Z][A-Za-z]+:)",
        openapi,
        re.MULTILINE | re.DOTALL,
    )
    openapi_codes = (
        set(re.findall(r"^        - ([A-Z][A-Z_]+)$", error_schema.group("body"), re.MULTILINE))
        if error_schema
        else set()
    )
    if source_codes != contract_codes or source_codes != openapi_codes:
        problems.append("Error codes differ between backend, errors.yaml, and openapi.yaml")

    if "openapi: 3.1.0" not in openapi:
        problems.append("contracts/openapi.yaml must declare OpenAPI 3.1.0")

    for problem in problems:
        print(f"contract-check: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"contract-check: {len(authored_paths)} paths and {len(source_codes)} error codes valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())