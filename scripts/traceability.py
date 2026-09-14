"""Deterministic requirement-traceability extraction and CSV rendering."""

from __future__ import annotations

import ast
import csv
import glob
import io
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = Path("docs/REQUIREMENTS.md")
METADATA_PATH = Path("project/traceability_metadata.json")
MATRIX_PATH = Path("project/TRACEABILITY.csv")
EXPECTED_COLUMNS = (
    "req_id",
    "title",
    "design_refs",
    "code_paths",
    "tests",
    "status",
    "phase",
    "last_verified",
)
ALLOWED_STATUS = frozenset({"implemented", "partial", "planned", "retired"})
REQUIREMENT_ID = re.compile(r"^(?:FR|NFR)-\d{3,4}$")
REQUIREMENT_ROW = re.compile(
    r"^\|\s*((?:FR|NFR)-\d{3,4})\s*\|\s*(.*?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
)
SOURCE_ANNOTATION = re.compile(r"^\s*(?:#|//)\s*trace:\s*(.*?)\s*$", re.IGNORECASE)
DOC_ANNOTATION = re.compile(r"^\s*<!--\s*trace:\s*(.*?)\s*-->\s*$", re.IGNORECASE)
TEST_ANNOTATION = re.compile(r"^\s*//\s*req:\s*(.*?)\s*$", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IGNORED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        "vendor",
        "vendors",
        ".artifacts",
    }
)
SOURCE_ROOTS = (
    Path("backend/app"),
    Path("backend/alembic"),
    Path("frontend/src"),
    Path("scripts"),
)
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".txt"})
PYTHON_TEST_ROOTS = (Path("backend/tests"), Path("scripts/tests"))
FRONTEND_TEST_ROOTS = (Path("frontend/src"), Path("frontend/scripts"))
FRONTEND_TEST_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs"})
DOC_ROOTS = (Path("docs"),)


class TraceabilityError(ValueError):
    """Raised when traceability metadata cannot be interpreted safely."""


@dataclass(frozen=True)
class Requirement:
    req_id: str
    title: str
    phase: str


@dataclass(frozen=True)
class Evidence:
    status: str
    phase: str
    last_verified: str


@dataclass(frozen=True)
class GeneratedTraceability:
    rows: tuple[dict[str, str], ...]
    csv_bytes: bytes
    source_annotations: int
    test_annotations: int
    document_annotations: int


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TraceabilityError(f"cannot read {path.as_posix()}: {exc}") from exc


def _repo_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True
    return any(part in IGNORED_PARTS or part.startswith(".venv-") for part in parts)


def _iter_files(
    root: Path, roots: Sequence[Path], suffixes: frozenset[str]
) -> Iterable[Path]:
    for relative_root in roots:
        directory = root / relative_root
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in suffixes and not _ignored(path, root):
                yield path


def _parse_ids(
    raw: str, *, location: str, known_ids: frozenset[str]
) -> tuple[str, ...]:
    values = tuple(part.strip() for part in raw.split(","))
    if not values or any(not value for value in values):
        raise TraceabilityError(f"{location}: malformed trace annotation")
    malformed = [value for value in values if not REQUIREMENT_ID.fullmatch(value)]
    if malformed:
        raise TraceabilityError(
            f"{location}: malformed requirement id {malformed[0]!r}"
        )
    unknown = [value for value in values if value not in known_ids]
    if unknown:
        raise TraceabilityError(f"{location}: unknown requirement id {unknown[0]}")
    if len(set(values)) != len(values):
        duplicate = next(
            value for index, value in enumerate(values) if value in values[:index]
        )
        raise TraceabilityError(f"{location}: duplicate requirement id {duplicate}")
    return values


def _ids_from_req_decorators(
    decorators: Sequence[ast.expr], *, path: str, known_ids: frozenset[str]
) -> tuple[tuple[str, ...], int]:
    raw_ids: list[str] = []
    count = 0
    for decorator in decorators:
        values = _req_call(decorator, path=path)
        if values is not None:
            raw_ids.extend(values)
            count += 1
    if not count:
        return (), 0
    return (
        _parse_ids(",".join(raw_ids), location=path, known_ids=known_ids),
        count,
    )


def parse_requirements(path: Path) -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}
    for line_number, line in enumerate(_read(path).splitlines(), start=1):
        match = REQUIREMENT_ROW.match(line)
        if match:
            req_id, wording, _, phase = match.groups()
            if req_id in requirements:
                raise TraceabilityError(
                    f"{path.as_posix()}:{line_number}: duplicate requirement definition {req_id}"
                )
            requirements[req_id] = Requirement(
                req_id, requirement_title(wording), phase.strip()
            )
            continue
        if re.match(r"^\|\s*(?:FR|NFR)-", line, re.IGNORECASE):
            candidate = line.split("|", 2)[1].strip()
            raise TraceabilityError(
                f"{path.as_posix()}:{line_number}: malformed requirement definition {candidate!r}"
            )
    if not requirements:
        raise TraceabilityError(f"{path.as_posix()}: no requirement definitions found")
    return requirements


def requirement_title(wording: str) -> str:
    """Produce a stable short title from normative requirement prose."""
    text = re.sub(r"\*\*([^*]+)\.\*\*\s*", r"\1: ", wording)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\b(?:MUST|MAY|SHOULD|NOT)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:1].upper() + text[1:]


def load_evidence(path: Path, known_ids: frozenset[str]) -> dict[str, Evidence]:
    try:
        raw = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        raise TraceabilityError(
            f"{path.as_posix()}: malformed JSON: {exc.msg}"
        ) from exc
    if not isinstance(raw, dict):
        raise TraceabilityError(f"{path.as_posix()}: expected an object")
    evidence: dict[str, Evidence] = {}
    for req_id, item in raw.items():
        if req_id not in known_ids:
            raise TraceabilityError(
                f"{path.as_posix()}: unknown requirement id {req_id}"
            )
        if not isinstance(item, dict) or set(item) != {
            "status",
            "phase",
            "last_verified",
        }:
            raise TraceabilityError(f"{path.as_posix()}: invalid metadata for {req_id}")
        status = item.get("status")
        phase = item.get("phase")
        last_verified = item.get("last_verified")
        if status not in ALLOWED_STATUS:
            raise TraceabilityError(
                f"{path.as_posix()}: invalid status for {req_id}: {status!r}"
            )
        if not isinstance(phase, str) or not phase:
            raise TraceabilityError(f"{path.as_posix()}: invalid phase for {req_id}")
        if not isinstance(last_verified, str):
            raise TraceabilityError(
                f"{path.as_posix()}: invalid last_verified for {req_id}"
            )
        evidence[req_id] = Evidence(status, phase, last_verified)
    missing = sorted(known_ids.difference(evidence))
    if missing:
        preview = ", ".join(missing[:5])
        suffix = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
        raise TraceabilityError(
            f"{path.as_posix()}: missing metadata for {preview}{suffix}"
        )
    return evidence


def github_anchor(title: str) -> str:
    value = re.sub(r"<[^>]+>", "", title).strip().lower()
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "-", value)
    return re.sub(r"-+", "-", value).strip("-")


def parse_document_annotations(
    root: Path, known_ids: frozenset[str], roots: Sequence[Path] = DOC_ROOTS
) -> tuple[dict[str, set[str]], int]:
    mappings = {req_id: set() for req_id in known_ids}
    count = 0
    for path in _iter_files(root, roots, frozenset({".md"})):
        lines = _read(path).splitlines()
        headings: list[tuple[int, str]] = []
        for index, line in enumerate(lines):
            match = HEADING.match(line)
            if match and not line.lstrip().startswith("# trace:"):
                headings.append((index, github_anchor(match.group(2))))
        for index, line in enumerate(lines):
            if "<!--" not in line or "trace:" not in line.lower():
                continue
            match = DOC_ANNOTATION.fullmatch(line)
            location = f"{_repo_path(root, path)}:{index + 1}"
            if not match:
                raise TraceabilityError(
                    f"{location}: malformed documentation trace annotation"
                )
            requirement_ids = _parse_ids(
                match.group(1), location=location, known_ids=known_ids
            )
            following = next(
                (heading for heading in headings if heading[0] > index), None
            )
            preceding = next(
                (heading for heading in reversed(headings) if heading[0] < index), None
            )
            if following is not None and all(
                not lines[pos].strip() for pos in range(index + 1, following[0])
            ):
                anchor = following[1]
            elif preceding is not None:
                anchor = preceding[1]
            else:
                raise TraceabilityError(
                    f"{location}: annotation has no associated Markdown heading"
                )
            reference = f"{_repo_path(root, path)}#{anchor}"
            for req_id in requirement_ids:
                mappings[req_id].add(reference)
            count += 1
    return mappings, count


def _python_symbol_lines(path: Path) -> set[int]:
    try:
        tree = ast.parse(_read(path), filename=path.as_posix())
    except SyntaxError as exc:
        raise TraceabilityError(
            f"{path.as_posix()}:{exc.lineno}: invalid Python syntax"
        ) from exc
    return {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _text_symbol_lines(path: Path, lines: Sequence[str]) -> set[int]:
    if path.suffix == ".txt":
        return {index for index, line in enumerate(lines, start=1) if line.strip()}
    expression = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"(?:function|class|const|let|var|interface|type)\s+[A-Za-z_$][\w$]*"
    )
    symbols = {
        index for index, line in enumerate(lines, start=1) if expression.match(line)
    }
    if path.suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
        symbols.update(
            index
            for index, line in enumerate(lines, start=1)
            if re.match(
                r"^\s*[A-Za-z_$][\w$]*\s*:\s*(?:async\s+)?(?:function|class|\()", line
            )
        )
    return symbols


def parse_source_annotations(
    root: Path, known_ids: frozenset[str], roots: Sequence[Path] = SOURCE_ROOTS
) -> tuple[dict[str, set[str]], int]:
    mappings = {req_id: set() for req_id in known_ids}
    count = 0
    for path in _iter_files(root, roots, SOURCE_SUFFIXES):
        lines = _read(path).splitlines()
        symbols = (
            _python_symbol_lines(path)
            if path.suffix == ".py"
            else _text_symbol_lines(path, lines)
        )
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if "trace:" not in line.lower() or not stripped.startswith(
                ("# trace:", "// trace:")
            ):
                continue
            match = SOURCE_ANNOTATION.fullmatch(line)
            location = f"{_repo_path(root, path)}:{index + 1}"
            if not match:
                raise TraceabilityError(
                    f"{location}: malformed source trace annotation"
                )
            requirement_ids = _parse_ids(
                match.group(1), location=location, known_ids=known_ids
            )
            next_line = index + 2
            while next_line <= len(lines) and not lines[next_line - 1].strip():
                next_line += 1
            if next_line not in symbols:
                raise TraceabilityError(
                    f"{location}: source annotation is not followed by an implementation symbol"
                )
            reference = _repo_path(root, path)
            for req_id in requirement_ids:
                mappings[req_id].add(reference)
            count += 1
    return mappings, count


def _req_call(node: ast.AST, *, path: str) -> tuple[str, ...] | None:
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.func.id != "req"
    ):
        return None
    if node.keywords or not node.args:
        raise TraceabilityError(f"{path}:{node.lineno}: malformed @req decorator")
    values: list[str] = []
    for argument in node.args:
        if not isinstance(argument, ast.Constant) or not isinstance(
            argument.value, str
        ):
            raise TraceabilityError(
                f"{path}:{node.lineno}: @req arguments must be string literals"
            )
        values.append(argument.value)
    return tuple(values)


def _walk_python_tests(
    body: Sequence[ast.stmt], parents: tuple[str, ...] = ()
) -> Iterable[tuple[ast.FunctionDef | ast.AsyncFunctionDef, tuple[str, ...]]]:
    for node in body:
        if isinstance(node, ast.ClassDef):
            yield from _walk_python_tests(node.body, (*parents, node.name))
        elif isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("test_"):
            yield node, parents


def _parse_python_test_annotations(
    root: Path,
    known_ids: frozenset[str],
    mappings: dict[str, set[str]],
    roots: Sequence[Path],
) -> tuple[int, list[str]]:
    count = 0
    uncited: list[str] = []
    for path in _iter_files(root, roots, frozenset({".py"})):
        relative = _repo_path(root, path)
        try:
            tree = ast.parse(_read(path), filename=relative)
        except SyntaxError as exc:
            raise TraceabilityError(
                f"{relative}:{exc.lineno}: invalid Python syntax"
            ) from exc

        module_ids: tuple[str, ...] = ()
        module_decorators = 0
        for statement in tree.body:
            if not isinstance(statement, ast.Assign) or not any(
                isinstance(target, ast.Name) and target.id == "pytestmark"
                for target in statement.targets
            ):
                continue
            markers = (
                statement.value.elts
                if isinstance(statement.value, (ast.List, ast.Tuple))
                else (statement.value,)
            )
            module_ids, module_decorators = _ids_from_req_decorators(
                markers, path=f"{relative}:{statement.lineno}", known_ids=known_ids
            )
        for node, parents in _walk_python_tests(tree.body):
            node_id = "::".join((relative, *parents, node.name))
            ids, decorators = _ids_from_req_decorators(
                node.decorator_list,
                path=f"{relative}:{node.lineno}",
                known_ids=known_ids,
            )
            if decorators == 0:
                ids = module_ids
                decorators = module_decorators
                if decorators == 0:
                    uncited.append(node_id)
                    continue
            for req_id in ids:
                mappings[req_id].add(node_id)
            count += decorators
    return count, uncited


def _javascript_test_calls(text: str) -> list[tuple[int, int, str]]:
    """Return Vitest/Jest test call locations using a small lexical scanner."""
    calls: list[tuple[int, int, str]] = []
    expression = re.compile(
        r"\b(?:it|test)(?:\.(?:skip|todo|only|concurrent))?\s*\(\s*"
        r"(?P<quote>['\"`])(?P<title>.*?)(?P=quote)",
        re.DOTALL,
    )
    for match in expression.finditer(text):
        prefix = text[: match.start()]
        line = prefix.count("\n") + 1
        column = match.start() - prefix.rfind("\n") - 1
        calls.append((line, column, re.sub(r"\s+", " ", match.group("title")).strip()))
    return calls


def _parse_frontend_test_annotations(
    root: Path,
    known_ids: frozenset[str],
    mappings: dict[str, set[str]],
    roots: Sequence[Path],
) -> tuple[int, list[str]]:
    count = 0
    uncited: list[str] = []
    for path in _iter_files(root, roots, FRONTEND_TEST_SUFFIXES):
        if ".test." not in path.name:
            continue
        relative = _repo_path(root, path)
        text = _read(path)
        lines = text.splitlines()
        calls = _javascript_test_calls(text)
        call_lines = {line for line, _, _ in calls}
        annotations: dict[int, tuple[str, ...]] = {}
        for index, line in enumerate(lines, start=1):
            if "req:" not in line.lower():
                continue
            match = TEST_ANNOTATION.fullmatch(line)
            location = f"{relative}:{index}"
            if not match:
                raise TraceabilityError(
                    f"{location}: malformed frontend test annotation"
                )
            next_line = index + 1
            while next_line <= len(lines) and not lines[next_line - 1].strip():
                next_line += 1
            if next_line not in call_lines:
                raise TraceabilityError(
                    f"{location}: frontend test annotation is not followed by an it()/test() call"
                )
            if next_line in annotations:
                raise TraceabilityError(
                    f"{location}: duplicate annotation for frontend test"
                )
            annotations[next_line] = _parse_ids(
                match.group(1), location=location, known_ids=known_ids
            )
        for line, column, title in calls:
            node_id = f"{relative}::{line}:{column}::{title}"
            ids = annotations.get(line)
            if ids is None:
                uncited.append(node_id)
                continue
            for req_id in ids:
                mappings[req_id].add(node_id)
            count += 1
    return count, uncited


def parse_test_annotations(
    root: Path,
    known_ids: frozenset[str],
    python_roots: Sequence[Path] = PYTHON_TEST_ROOTS,
    frontend_roots: Sequence[Path] = FRONTEND_TEST_ROOTS,
) -> tuple[dict[str, set[str]], int, tuple[str, ...]]:
    mappings = {req_id: set() for req_id in known_ids}
    python_count, uncited = _parse_python_test_annotations(
        root, known_ids, mappings, python_roots
    )
    frontend_count, frontend_uncited = _parse_frontend_test_annotations(
        root, known_ids, mappings, frontend_roots
    )
    uncited.extend(frontend_uncited)
    return mappings, python_count + frontend_count, tuple(sorted(uncited))


def render_csv(rows: Sequence[Mapping[str, str]]) -> bytes:
    """Render canonical UTF-8 CSV bytes with repository-independent LF endings."""

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EXPECTED_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def generate(root: Path = ROOT, *, enforce_tr2: bool = True) -> GeneratedTraceability:
    requirements = parse_requirements(root / REQUIREMENTS_PATH)
    known_ids = frozenset(requirements)
    evidence = load_evidence(root / METADATA_PATH, known_ids)
    doc_mappings, doc_count = parse_document_annotations(root, known_ids)
    source_mappings, source_count = parse_source_annotations(root, known_ids)
    test_mappings, test_count, uncited = parse_test_annotations(root, known_ids)
    if enforce_tr2 and uncited:
        preview = ", ".join(uncited[:5])
        suffix = f" (and {len(uncited) - 5} more)" if len(uncited) > 5 else ""
        raise TraceabilityError(
            f"TR-2: tests without requirement citations: {preview}{suffix}"
        )
    rows: list[dict[str, str]] = []
    for req_id in sorted(requirements):
        requirement = requirements[req_id]
        item = evidence[req_id]
        rows.append(
            {
                "req_id": req_id,
                "title": requirement.title,
                "design_refs": "|".join(sorted(doc_mappings[req_id])),
                "code_paths": "|".join(sorted(source_mappings[req_id])),
                "tests": "|".join(sorted(test_mappings[req_id])),
                "status": item.status,
                "phase": item.phase,
                "last_verified": item.last_verified,
            }
        )
    return GeneratedTraceability(
        tuple(rows), render_csv(rows), source_count, test_count, doc_count
    )


def validate_rows(root: Path, rows: Sequence[Mapping[str, str]]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        req_id = row.get("req_id", "")
        if req_id in seen:
            problems.append(f"line {line_number}: duplicate requirement {req_id}")
        seen.add(req_id)
        if row.get("status") not in ALLOWED_STATUS:
            problems.append(f"line {line_number}: invalid status {row.get('status')!r}")
        if not row.get("phase"):
            problems.append(f"line {line_number}: phase is required")
        for reference in filter(None, row.get("design_refs", "").split("|")):
            target, separator, anchor = reference.partition("#")
            path = root / target
            if not path.is_file():
                problems.append(f"line {line_number}: missing design file {target}")
            elif not separator or not anchor:
                problems.append(
                    f"line {line_number}: design ref lacks anchor: {reference}"
                )
            else:
                anchors = {
                    github_anchor(match.group(2))
                    for line in _read(path).splitlines()
                    if (match := HEADING.match(line))
                    and not line.lstrip().startswith("# trace:")
                }
                if anchor not in anchors:
                    problems.append(
                        f"line {line_number}: missing design anchor {reference}"
                    )
        for code_path in filter(None, row.get("code_paths", "").split("|")):
            if not glob.glob(str(root / code_path)):
                problems.append(
                    f"line {line_number}: code path resolves to nothing: {code_path}"
                )
        for test_ref in filter(None, row.get("tests", "").split("|")):
            test_path, separator, node_name = test_ref.partition("::")
            target = root / test_path
            if not target.is_file():
                problems.append(f"line {line_number}: missing test file {test_path}")
            elif not separator or not node_name:
                problems.append(
                    f"line {line_number}: test ref lacks node id: {test_ref}"
                )
            elif target.suffix == ".py":
                try:
                    tree = ast.parse(_read(target), filename=test_path)
                except SyntaxError:
                    problems.append(
                        f"line {line_number}: invalid Python test file {test_path}"
                    )
                    continue
                names = {
                    "::".join((*parents, node.name))
                    for node, parents in _walk_python_tests(tree.body)
                }
                if node_name not in names:
                    problems.append(
                        f"line {line_number}: missing Python test node {test_ref}"
                    )
            else:
                match = re.match(
                    r"(?P<line>\d+):(?P<column>\d+)::(?P<title>.+)$", node_name
                )
                if not match:
                    problems.append(
                        f"line {line_number}: invalid frontend test node id: {test_ref}"
                    )
                    continue
                calls = {
                    (line, column, title)
                    for line, column, title in _javascript_test_calls(_read(target))
                }
                expected = (
                    int(match.group("line")),
                    int(match.group("column")),
                    match.group("title"),
                )
                if expected not in calls:
                    problems.append(
                        f"line {line_number}: missing frontend test node {test_ref}"
                    )
    return problems
