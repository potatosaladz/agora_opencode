"""Schema-level checks for the canonical identity and membership model."""

from pathlib import Path

from sqlalchemy import Enum

from app.db.models.identity import User, WorkspaceMember
from app.ports.auth import WorkspaceRole
from tests.traceability import req


@req("FR-109", "NFR-010")
def test_workspace_role_vocabulary_is_exact_and_canonical() -> None:
    assert [role.value for role in WorkspaceRole] == [
        "ADMIN",
        "RESEARCHER",
        "OPERATOR",
        "VIEWER",
    ]
    role_type = WorkspaceMember.__table__.c.role.type
    assert isinstance(role_type, Enum)
    assert role_type.name == "workspace_role"
    assert role_type.enums == ["ADMIN", "RESEARCHER", "OPERATOR", "VIEWER"]


@req("FR-109", "NFR-010")
def test_users_have_external_identity_but_no_local_password_or_platform_role() -> None:
    columns = set(User.__table__.c.keys())
    assert {"oidc_issuer", "oidc_subject", "is_active"} <= columns
    assert "password_hash" not in columns
    assert "role_platform" not in columns


@req("FR-109", "NFR-010")
def test_membership_migration_forces_fail_closed_workspace_rls() -> None:
    migration = (
        Path(__file__).parents[2] / "alembic" / "versions" / "20260904_0003_auth_rbac.py"
    ).read_text(encoding="utf-8")

    assert "ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY" in migration
    assert "ALTER TABLE workspace_members FORCE ROW LEVEL SECURITY" in migration
    assert "current_setting('app.workspace_id', true)" in migration
    assert "WITH CHECK" in migration
