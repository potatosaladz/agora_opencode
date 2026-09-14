"""Focused tests for deterministic traceability parsing and rendering."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from traceability import (
    Evidence,
    TraceabilityError,
    _parse_ids,
    generate,
    load_evidence,
    parse_source_annotations,
    parse_test_annotations,
    render_csv,
)

KNOWN = frozenset({"FR-101", "NFR-016"})
T = TypeVar("T", bound=Callable[..., object])


def req(*_requirement_ids: str) -> Callable[[T], T]:
    """Keep these dependency-free tool tests legible to the traceability parser."""

    return lambda function: function


@req("NFR-018")
def test_requirement_ids_reject_unknown_malformed_and_empty_values() -> None:
    with pytest.raises(TraceabilityError, match="unknown requirement"):
        _parse_ids("FR-999", location="sample:1", known_ids=KNOWN)
    with pytest.raises(TraceabilityError, match="malformed requirement"):
        _parse_ids("FR-1", location="sample:1", known_ids=KNOWN)
    with pytest.raises(TraceabilityError, match="malformed trace annotation"):
        _parse_ids("FR-101,", location="sample:1", known_ids=KNOWN)
    with pytest.raises(TraceabilityError, match="duplicate requirement id FR-101"):
        _parse_ids("FR-101, FR-101", location="sample:1", known_ids=KNOWN)


@req("NFR-018")
def test_metadata_requires_exact_requirement_coverage(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "FR-101": {
                    "status": "planned",
                    "phase": "3",
                    "last_verified": "",
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TraceabilityError, match="missing metadata for NFR-016"):
        load_evidence(path, KNOWN)


@req("NFR-018")
def test_metadata_rejects_unknown_requirements(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "FR-999": {
                    "status": "planned",
                    "phase": "3",
                    "last_verified": "",
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TraceabilityError, match="unknown requirement id FR-999"):
        load_evidence(path, KNOWN)


@req("NFR-018")
def test_source_annotation_must_target_the_next_symbol(tmp_path: Path) -> None:
    source = tmp_path / "app"
    source.mkdir()
    (source / "bad.py").write_text(
        "# trace: FR-101\n# unrelated explanation\ndef implementation():\n    pass\n",
        encoding="utf-8",
    )
    with pytest.raises(
        TraceabilityError, match="not followed by an implementation symbol"
    ):
        parse_source_annotations(tmp_path, KNOWN, (Path("app"),))


@req("NFR-018")
def test_frontend_annotations_are_explicit_and_duplicate_titles_are_unambiguous(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "frontend"
    tests.mkdir()
    (tests / "sample.test.ts").write_text(
        "// req: FR-101\n"
        'it("same title", () => {});\n'
        "// req: NFR-016\n"
        'it("same title", () => {});\n',
        encoding="utf-8",
    )
    mappings, count, uncited = parse_test_annotations(
        tmp_path, KNOWN, python_roots=(), frontend_roots=(Path("frontend"),)
    )
    assert count == 2
    assert not uncited
    assert mappings["FR-101"] == {"frontend/sample.test.ts::2:0::same title"}
    assert mappings["NFR-016"] == {"frontend/sample.test.ts::4:0::same title"}


@req("NFR-018")
def test_frontend_uncited_and_misattached_annotations_are_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "frontend"
    tests.mkdir()
    path = tests / "sample.test.ts"
    path.write_text('it("uncited", () => {});\n', encoding="utf-8")
    _, _, uncited = parse_test_annotations(
        tmp_path, KNOWN, python_roots=(), frontend_roots=(Path("frontend"),)
    )
    assert uncited == ("frontend/sample.test.ts::1:0::uncited",)

    path.write_text(
        '// req: FR-101\nconst helper = true;\nit("test", () => {});\n',
        encoding="utf-8",
    )
    with pytest.raises(
        TraceabilityError, match=r"not followed by an it\(\)/test\(\) call"
    ):
        parse_test_annotations(
            tmp_path, KNOWN, python_roots=(), frontend_roots=(Path("frontend"),)
        )


@req("NFR-018")
def test_python_module_requirement_marker_applies_to_each_test(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_module.py").write_text(
        "pytestmark = req('FR-101')\n\n"
        "def test_first():\n    pass\n\n"
        "def test_second():\n    pass\n",
        encoding="utf-8",
    )
    mappings, count, uncited = parse_test_annotations(
        tmp_path, KNOWN, python_roots=(Path("tests"),), frontend_roots=()
    )
    assert count == 2
    assert not uncited
    assert mappings["FR-101"] == {
        "tests/test_module.py::test_first",
        "tests/test_module.py::test_second",
    }


@req("NFR-018")
def test_generation_covers_requirements_in_stable_id_order(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "project").mkdir()
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "tests").mkdir()
    (tmp_path / "docs" / "REQUIREMENTS.md").write_text(
        "<!-- trace: NFR-016, FR-101 -->\n"
        "# Requirements\n\n"
        "| ID | Requirement | P | Ph | V |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| NFR-016 | Testability. Works offline | P0 | 1 | T |\n"
        "| FR-101 | Open a session | P0 | 3 | T |\n",
        encoding="utf-8",
    )
    (tmp_path / "project" / "traceability_metadata.json").write_text(
        json.dumps(
            {
                "NFR-016": {"status": "planned", "phase": "1", "last_verified": ""},
                "FR-101": {"status": "planned", "phase": "3", "last_verified": ""},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "feature.py").write_text(
        "# trace: NFR-016, FR-101\ndef feature():\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "tests" / "test_feature.py").write_text(
        "@req('NFR-016', 'FR-101')\ndef test_feature():\n    pass\n",
        encoding="utf-8",
    )

    first = generate(tmp_path)
    second = generate(tmp_path)

    assert [row["req_id"] for row in first.rows] == ["FR-101", "NFR-016"]
    assert first.csv_bytes == second.csv_bytes


@req("NFR-018")
def test_csv_rendering_is_byte_deterministic_and_uses_lf() -> None:
    row = {
        "req_id": "FR-101",
        "title": "Title",
        "design_refs": "docs/FILE.md#section",
        "code_paths": "app/file.py",
        "tests": "tests/test_file.py::test_case",
        "status": Evidence("implemented", "3", "run").status,
        "phase": "3",
        "last_verified": "run",
    }
    first = render_csv([row])
    second = render_csv([row])
    assert first == second
    assert b"\r\n" not in first
