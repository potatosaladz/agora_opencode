"""Executable import-boundary rules for the backend package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.traceability import req

# Each layer may import itself and only the listed app-level packages. External imports
# remain governed by Ruff/mypy; this table enforces the inward architecture of ADR-012.
_ALLOWED_APP_IMPORTS: dict[str, frozenset[str]] = {
    "adapters": frozenset(
        {"adapters", "common", "config", "contracts", "domain", "observability", "ports"}
    ),
    "api": frozenset(
        {
            "api",
            "application",
            "common",
            "composition",
            "config",
            "contracts",
            "domain",
            "observability",
            "ports",
            "security",
        }
    ),
    "application": frozenset({"application", "common", "domain", "ports"}),
    "common": frozenset({"common"}),
    "composition": frozenset(
        {
            "adapters",
            "api",
            "application",
            "common",
            "composition",
            "config",
            "contracts",
            "db",
            "domain",
            "observability",
            "ports",
            "security",
        }
    ),
    "config": frozenset({"common", "config"}),
    "contracts": frozenset({"common", "contracts"}),
    "db": frozenset({"common", "config", "contracts", "db", "domain", "ports"}),
    "domain": frozenset({"common", "domain", "ports"}),
    "expert_prompts": frozenset({"expert_prompts"}),
    "observability": frozenset({"common", "config", "observability"}),
    "ports": frozenset({"common", "ports"}),
    "security": frozenset({"common", "domain", "ports", "security"}),
}


# Provider/infrastructure SDKs must never appear outside `app/adapters/`. This list is the
# executable half of the mypy overrides table in pyproject.toml: add a name to both places.
_SDK_MODULES = frozenset(
    {"asyncpg", "minio", "nats", "pgvector", "prometheus_client", "temporalio", "z3"}
)


def _imported_top_level_modules(tree: ast.AST) -> set[str]:
    """Collect the first component of every top-level import statement in a module."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            modules.add(node.module.split(".", 1)[0])
    return modules


def find_sdk_violations(app_root: Path) -> list[str]:
    """Return human-readable provider-SDK import sites found below an ``app`` package root."""
    violations: list[str] = []
    for source_path in sorted(app_root.rglob("*.py")):
        relative_path = source_path.relative_to(app_root)
        if len(relative_path.parts) == 1:
            continue
        if relative_path.parts[0] == "adapters":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for name in sorted(_imported_top_level_modules(tree) & _SDK_MODULES):
            violations.append(
                f"{relative_path.as_posix()}: provider SDK {name!r} must only be imported "
                "under app/adapters/"
            )
    return violations


@req("NFR-012")
def test_no_provider_sdk_import_outside_adapters() -> None:
    app_root = Path(__file__).parents[1] / "app"

    assert find_sdk_violations(app_root) == []


@req("NFR-012")
@pytest.mark.parametrize(
    ("relative_path", "source", "module"),
    [
        (
            "domain/plan.py",
            "import minio  # deliberated by the import-lint test itself\n",
            "minio",
        ),
        (
            "application/use_case.py",
            "from prometheus_client import Counter  # deliberated by the import-lint test\n",
            "prometheus_client",
        ),
        (
            "ports/llm.py",
            "from nats.js.client import JetStreamContext  # deliberated by the import-lint test\n",
            "nats",
        ),
    ],
)
def test_sdk_lint_rejects_deliberate_sdk_import(
    tmp_path: Path, relative_path: str, source: str, module: str
) -> None:
    app_root = tmp_path / "app"
    source_path = app_root / relative_path
    source_path.parent.mkdir(parents=True)
    source_path.write_text(source, encoding="utf-8")

    violations = find_sdk_violations(app_root)
    assert len(violations) == 1
    assert f"provider SDK {module!r}" in violations[0]


@req("NFR-012")
def test_sdk_lint_accepts_adapter_sdk_import(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    source_path = app_root / "adapters" / "minio" / "object_store.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "from minio import Minio\nfrom minio.error import S3Error\n", encoding="utf-8"
    )

    assert find_sdk_violations(app_root) == []


def _imported_app_layers(node: ast.Import | ast.ImportFrom, relative_path: Path) -> set[str]:
    modules: list[str] = []
    if isinstance(node, ast.Import):
        modules.extend(alias.name for alias in node.names)
    elif node.level == 0:
        if node.module == "app":
            modules.extend(f"app.{alias.name}" for alias in node.names)
        elif node.module is not None:
            modules.append(node.module)
    else:
        package = ["app", *relative_path.parent.parts]
        prefix = package[: len(package) - node.level + 1]
        if node.module is not None:
            modules.append(".".join([*prefix, node.module]))
        else:
            modules.extend(".".join([*prefix, alias.name]) for alias in node.names)

    return {
        parts[1]
        for module in modules
        if (parts := module.split(".")) and len(parts) > 1 and parts[0] == "app"
    }


def find_layer_violations(app_root: Path) -> list[str]:
    """Return stable, human-readable violations found below an ``app`` package root."""
    violations: list[str] = []
    for source_path in sorted(app_root.rglob("*.py")):
        relative_path = source_path.relative_to(app_root)
        if len(relative_path.parts) == 1:
            continue

        importer = relative_path.parts[0]
        allowed = _ALLOWED_APP_IMPORTS.get(importer)
        if allowed is None:
            violations.append(f"{relative_path.as_posix()}: unregistered app layer {importer!r}")
            continue

        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            for imported in sorted(_imported_app_layers(node, relative_path) - allowed):
                violations.append(
                    f"{relative_path.as_posix()}:{node.lineno}: "
                    f"app.{importer} must not import app.{imported}"
                )
    return violations


@req("NFR-012")
def test_backend_obeys_import_boundaries() -> None:
    app_root = Path(__file__).parents[1] / "app"

    assert find_layer_violations(app_root) == []


@req("NFR-012")
@pytest.mark.parametrize(
    "source",
    [
        "from app.adapters.inmemory.cache import InMemoryCache\n",
        "from ..adapters.inmemory.cache import InMemoryCache\n",
    ],
)
def test_import_lint_rejects_deliberate_forbidden_import(tmp_path: Path, source: str) -> None:
    app_root = tmp_path / "app"
    domain = app_root / "domain"
    domain.mkdir(parents=True)
    (domain / "bad.py").write_text(source, encoding="utf-8")

    assert find_layer_violations(app_root) == [
        "domain/bad.py:1: app.domain must not import app.adapters"
    ]


@req("NFR-012")
@pytest.mark.parametrize(
    ("relative_path", "source"),
    [
        ("ports/contracts.py", "from app.common.errors import DomainError\n"),
        ("domain/model.py", "from app.ports.health import HealthStatus\n"),
        ("application/use_case.py", "from app.domain import __doc__\n"),
        ("composition/root.py", "from app.adapters import __doc__\n"),
    ],
)
def test_import_lint_accepts_allowed_imports(
    tmp_path: Path, relative_path: str, source: str
) -> None:
    app_root = tmp_path / "app"
    source_path = app_root / relative_path
    source_path.parent.mkdir(parents=True)
    source_path.write_text(source, encoding="utf-8")

    assert find_layer_violations(app_root) == []
