"""MinIO `ObjectStore` adapter with digest verification and bounded SDK calls."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from datetime import timedelta
from io import BytesIO
from typing import Any, ParamSpec, TypeVar, cast

from minio import Minio
from minio.error import MinioException, S3Error

from app.ports.errors import (
    IntegrityObjectError,
    NotFoundObjectError,
    PermanentPortError,
    TransientPortError,
)
from app.ports.health import HealthStatus
from app.ports.storage import ObjectRef, ObjectStore

__all__ = ["MinioObjectStore"]

_PORT = "object_store"
_MODES = frozenset({"read", "write"})
_NOT_FOUND_CODES = frozenset({"NoSuchBucket", "NoSuchKey", "NoSuchObject", "NotFound"})
_PERMANENT_CODES = frozenset(
    {
        "AccessDenied",
        "AuthorizationHeaderMalformed",
        "InvalidAccessKeyId",
        "InvalidBucketName",
        "InvalidRequest",
        "SignatureDoesNotMatch",
    }
)
P = ParamSpec("P")
T = TypeVar("T")


def _digest_of(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


class MinioObjectStore:
    """Store immutable artifact bytes in an S3-compatible MinIO deployment.

    The synchronous SDK runs in worker threads and each call is bounded from the
    caller's perspective. This adapter never creates buckets or changes policies.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        *,
        secure: bool = False,
        bucket: str = "agora-artifacts",
        operation_timeout_s: float = 10.0,
        client: Any | None = None,
    ) -> None:
        if operation_timeout_s <= 0:
            raise ValueError("operation_timeout_s must be positive")
        self._client: Any = client or Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket
        self._operation_timeout_s = operation_timeout_s

    async def put(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> ObjectRef:
        self._validate_location(bucket, key)
        payload = bytes(body)
        digest = _digest_of(payload)
        object_metadata = dict(metadata)
        object_metadata["agora-sha256"] = digest.removeprefix("sha256:")
        await self._call(
            self._client.put_object,
            bucket,
            key,
            BytesIO(payload),
            len(payload),
            content_type=content_type,
            metadata=object_metadata,
        )
        return ObjectRef(
            bucket=bucket,
            key=key,
            digest=digest,
            content_type=content_type,
            size=len(payload),
        )

    async def get(self, ref: ObjectRef) -> bytes:
        response = await self._call(self._client.get_object, ref.bucket, ref.key)
        body = await self._call(self._read_and_close, response)
        digest = _digest_of(body)
        if ref.digest and ref.digest != digest:
            raise IntegrityObjectError(
                f"digest mismatch for {ref.bucket}/{ref.key}: "
                f"asked for {ref.digest}, received {digest}",
                port=_PORT,
            )
        return body

    async def presign(self, ref: ObjectRef, *, mode: str, ttl_s: int) -> str:
        if mode not in _MODES:
            raise PermanentPortError(f"unsupported presign mode {mode!r}", port=_PORT)
        if ttl_s <= 0:
            raise PermanentPortError("presigned URLs must expire", port=_PORT)
        expires = timedelta(seconds=ttl_s)
        if mode == "read":
            await self._call(self._client.stat_object, ref.bucket, ref.key)
            result = await self._call(
                self._client.presigned_get_object, ref.bucket, ref.key, expires=expires
            )
        else:
            result = await self._call(
                self._client.presigned_put_object, ref.bucket, ref.key, expires=expires
            )
        return cast(str, result)

    async def delete(self, ref: ObjectRef) -> None:
        await self._call(self._client.remove_object, ref.bucket, ref.key)

    async def health(self) -> HealthStatus:
        try:
            exists = await self._call(self._client.bucket_exists, self._bucket)
        except (PermanentPortError, TransientPortError):
            return HealthStatus.DOWN
        return HealthStatus.OK if exists else HealthStatus.DEGRADED

    async def close(self) -> None:
        """No-op: the SDK exposes no client close method."""

    @staticmethod
    def _validate_location(bucket: str, key: str) -> None:
        if not bucket or not key:
            raise PermanentPortError("bucket and key are both required", port=_PORT)

    @staticmethod
    def _read_and_close(response: Any) -> bytes:
        try:
            return cast(bytes, response.read())
        finally:
            response.close()
            response.release_conn()

    async def _call(self, operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(operation, *args, **kwargs),
                timeout=self._operation_timeout_s,
            )
        except TimeoutError as exc:
            raise TransientPortError("MinIO operation timed out", port=_PORT, cause=exc) from exc
        except S3Error as exc:
            if exc.code in _NOT_FOUND_CODES:
                raise NotFoundObjectError(
                    f"MinIO object not found: {exc.code}", port=_PORT, cause=exc
                ) from exc
            if exc.code in _PERMANENT_CODES or (
                exc.response is not None and exc.response.status < 500
            ):
                raise PermanentPortError(
                    f"MinIO rejected the operation: {exc.code}", port=_PORT, cause=exc
                ) from exc
            raise TransientPortError(
                f"MinIO service fault: {exc.code}", port=_PORT, cause=exc
            ) from exc
        except MinioException as exc:
            raise TransientPortError(f"MinIO protocol fault: {exc}", port=_PORT, cause=exc) from exc
        except (ConnectionError, OSError) as exc:
            raise TransientPortError(f"MinIO unreachable: {exc}", port=_PORT, cause=exc) from exc


_OBJECT_STORE_PORT: type[ObjectStore] = MinioObjectStore
