"""Secret providers. ADR-017 (Docker Swarm secrets), `docs/SECURITY.md` §4.

The rule that shapes both classes: **the application never writes a secret.** Creation is
`docker secret create`, done by an operator outside this process, so a compromised API can
never be the thing that plants a credential. `store` therefore exists on the port — the
Phase 13 user-supplied-provider-credentials flow needs it — but these infrastructure
providers refuse it. A provider that could both read and write platform credentials turns
one breach into a persistent one.

Both classes redact: every value that has been resolved is remembered and scrubbed from
`redact()` output and from the logging pipeline. That is what makes "never log a secret"
an implementation detail rather than a policy nobody reads.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from app.observability.logging import register_secret_literal
from app.ports.errors import PermanentPortError
from app.ports.health import HealthStatus
from app.ports.storage import SecretProvider, SecretRef

__all__ = ["EnvSecretProvider", "SwarmSecretProvider"]

_REDACTED = "[redacted]"


class _Remembering:
    """Shared bookkeeping: remember what was resolved so it can be scrubbed later."""

    def __init__(self) -> None:
        self._resolved: dict[str, str] = {}

    def _remember(self, name: str, value: str) -> str:
        self._resolved[name] = value
        register_secret_literal(value)
        return value

    def redact(self, text: str) -> str:
        result = text
        for value in self._resolved.values():
            if len(value) >= 4:
                result = result.replace(value, _REDACTED)
        return result


class EnvSecretProvider(_Remembering, SecretProvider):
    """Dev/test provider: reads named variables from the process environment.

    Selected by `SECRET_PROVIDER=env_file`. `startup_problems()` in settings makes it a
    fatal configuration error in production, because environment variables leak through
    `/proc`, `docker inspect`, crash dumps and CI logs.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        super().__init__()
        self._environ: Mapping[str, str] = environ if environ is not None else os.environ

    async def resolve(self, ref: SecretRef) -> str:
        if ref.provider != "env_file":
            raise PermanentPortError(
                f"env provider cannot resolve a {ref.provider!r} reference", port="secret_provider"
            )
        value = self._environ.get(ref.name)
        if value is None or value == "":
            raise PermanentPortError(f"secret {ref.name!r} is not set", port="secret_provider")
        return self._remember(ref.name, value)

    async def store(self, ref: SecretRef, value: str) -> None:
        raise PermanentPortError(
            "secrets are created out of band, never by the application (ADR-017)",
            port="secret_provider",
        )

    async def health(self) -> HealthStatus:
        return HealthStatus.OK


class SwarmSecretProvider(_Remembering, SecretProvider):
    """Production provider: reads files mounted under `/run/secrets`."""

    def __init__(self, path: Path = Path("/run/secrets")) -> None:
        super().__init__()
        self._path = path

    async def resolve(self, ref: SecretRef) -> str:
        if ref.provider != "swarm_secret":
            raise PermanentPortError(
                f"swarm provider cannot resolve a {ref.provider!r} reference",
                port="secret_provider",
            )
        # Reject traversal before touching the filesystem: a secret name arrives from a
        # request path in Phase 13, and `../../etc/passwd` must never be a legal name.
        if "/" in ref.name or "\\" in ref.name or ".." in ref.name:
            raise PermanentPortError(
                f"secret name {ref.name!r} is not a plain name", port="secret_provider"
            )
        candidate = self._path / ref.name
        if not candidate.is_file():
            raise PermanentPortError(
                f"secret {ref.name!r} is not mounted at {self._path}", port="secret_provider"
            )
        value = candidate.read_text(encoding="utf-8").strip()
        if not value:
            raise PermanentPortError(f"secret {ref.name!r} is empty", port="secret_provider")
        return self._remember(ref.name, value)

    async def store(self, ref: SecretRef, value: str) -> None:
        raise PermanentPortError(
            "secrets are created out of band, never by the application (ADR-017)",
            port="secret_provider",
        )

    async def health(self) -> HealthStatus:
        return HealthStatus.OK if self._path.is_dir() else HealthStatus.DOWN


#: mypy-checked structural conformance for both providers.
_SECRET_PORTS: tuple[type[SecretProvider], ...] = (EnvSecretProvider, SwarmSecretProvider)
