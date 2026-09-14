"""`ObjectStore` and `SecretProvider` ports — `docs/PORTS.md` §12."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.ports.health import HealthStatus

__all__ = ["ObjectRef", "ObjectStore", "SecretProvider", "SecretRef"]


class ObjectRef(BaseModel):
    """A pointer to a stored blob.

    `digest` is the sha256 of the body, computed by the caller and verified on read.
    `docs/REPRODUCIBILITY.md` requires that every artifact a session consumed be
    addressable by content, not just by key — a key can be overwritten, a digest cannot.
    """

    model_config = ConfigDict(frozen=True)

    bucket: str
    key: str
    digest: str = ""
    content_type: str = "application/octet-stream"
    size: int | None = None


class SecretRef(BaseModel):
    """A reference to a secret. The value never appears in this object.

    `docs/PORTS.md` §0: "Secrets never appear as arguments; only secret references cross a
    port boundary." A `SecretRef` that carried its value would make the rule unenforceable,
    so `extra="forbid"` plus a `value`-shaped name check keeps accidental leakage loud.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    name: str
    version: int | None = None


@runtime_checkable
class ObjectStore(Protocol):
    """Blob storage. Documents, datasets, raw LLM payloads, exports — never structured state."""

    async def put(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> ObjectRef: ...

    async def get(self, ref: ObjectRef) -> bytes: ...

    async def presign(self, ref: ObjectRef, *, mode: str, ttl_s: int) -> str: ...

    async def delete(self, ref: ObjectRef) -> None: ...

    async def health(self) -> HealthStatus: ...

    async def close(self) -> None: ...


@runtime_checkable
class SecretProvider(Protocol):
    """Resolve, store and redact secrets. ADR-017."""

    async def resolve(self, ref: SecretRef) -> str: ...

    async def store(self, ref: SecretRef, value: str) -> None: ...

    def redact(self, text: str) -> str: ...

    async def health(self) -> HealthStatus: ...
