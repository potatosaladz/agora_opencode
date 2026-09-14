"""In-memory `ObjectStore`. Content-addressed, digest-verified.

The interesting behaviour is the digest, not the storage. `docs/REPRODUCIBILITY.md` requires
that every artifact a session consumed be addressable by *content*: a key can be overwritten,
a digest cannot. So `put` computes sha256 over the exact bytes it was handed and `get`
re-verifies it before returning, which turns "the blob changed underneath us" from a silent
corruption into a `PermanentPortError`.

`presign` returns a URL that is not a signature. That is honest for tests and a lie in
production, which is why the composition root refuses to select this adapter outside
`environment=test` (see `app/composition/container.py`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from app.ports.errors import IntegrityObjectError, NotFoundObjectError, PermanentPortError
from app.ports.health import HealthStatus
from app.ports.storage import ObjectRef, ObjectStore

__all__ = ["InMemoryObjectStore"]

#: The only modes this platform ever presigns. Anything else is a caller bug.
MODES = frozenset({"read", "write"})


@dataclass(frozen=True)
class _Blob:
    body: bytes
    content_type: str
    metadata: Mapping[str, str]
    digest: str


def _digest_of(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


class InMemoryObjectStore:
    """A `bytes`-keyed dict that behaves like the MinIO adapter it stands in for."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], _Blob] = {}

    async def put(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> ObjectRef:
        if not bucket or not key:
            raise PermanentPortError("bucket and key are both required", port="object_store")
        digest = _digest_of(body)
        self._objects[(bucket, key)] = _Blob(
            body=bytes(body), content_type=content_type, metadata=dict(metadata), digest=digest
        )
        return ObjectRef(
            bucket=bucket, key=key, digest=digest, content_type=content_type, size=len(body)
        )

    async def get(self, ref: ObjectRef) -> bytes:
        blob = self._objects.get((ref.bucket, ref.key))
        if blob is None:
            raise NotFoundObjectError(f"{ref.bucket}/{ref.key} is not stored", port="object_store")
        if ref.digest and ref.digest != blob.digest:
            # The caller asked for a specific content and got something else. Returning it
            # would be the worst available outcome: a "reproduced" run that used other bytes.
            raise IntegrityObjectError(
                f"digest mismatch for {ref.bucket}/{ref.key}: "
                f"asked for {ref.digest}, stored {blob.digest}",
                port="object_store",
            )
        return blob.body

    async def presign(self, ref: ObjectRef, *, mode: str, ttl_s: int) -> str:
        if mode not in MODES:
            raise PermanentPortError(f"unsupported presign mode {mode!r}", port="object_store")
        if ttl_s <= 0:
            raise PermanentPortError("presigned URLs must expire", port="object_store")
        if (ref.bucket, ref.key) not in self._objects and mode == "read":
            raise NotFoundObjectError(f"{ref.bucket}/{ref.key} is not stored", port="object_store")
        return f"memory://{ref.bucket}/{ref.key}?mode={mode}&expires_in={ttl_s}"

    async def delete(self, ref: ObjectRef) -> None:
        """Idempotent, matching S3: deleting an absent key is not an error."""
        self._objects.pop((ref.bucket, ref.key), None)

    async def health(self) -> HealthStatus:
        return HealthStatus.OK

    async def close(self) -> None:
        self._objects.clear()


#: mypy-checked structural conformance; see `cache.py` for why this is a type alias.
_OBJECT_STORE_PORT: type[ObjectStore] = InMemoryObjectStore
