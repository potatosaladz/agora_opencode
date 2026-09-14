from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from minio.error import InvalidResponseError, S3Error

from app.adapters.minio.object_store import MinioObjectStore
from app.ports.errors import NotFoundObjectError, PermanentPortError, TransientPortError
from app.ports.health import HealthStatus
from app.ports.storage import ObjectRef
from tests.traceability import req


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _HttpResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[str, str] = {}
        self.response: _Response | None = None
        self.bucket_present = True
        self.failure: BaseException | None = None

    def _raise_failure(self) -> None:
        if self.failure is not None:
            raise self.failure

    def put_object(
        self,
        bucket: str,
        key: str,
        data: Any,
        length: int,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> object:
        self._raise_failure()
        body = bytes(data.read())
        assert len(body) == length
        assert content_type == "text/plain"
        self.objects[(bucket, key)] = body
        self.metadata = metadata
        return object()

    def get_object(self, bucket: str, key: str) -> _Response:
        self._raise_failure()
        self.response = _Response(self.objects[(bucket, key)])
        return self.response

    def stat_object(self, bucket: str, key: str) -> object:
        self._raise_failure()
        if (bucket, key) not in self.objects:
            raise _s3_error("NoSuchKey", 404)
        return object()

    def presigned_get_object(self, bucket: str, key: str, *, expires: timedelta) -> str:
        return f"https://minio/{bucket}/{key}?read={expires.total_seconds():.0f}"

    def presigned_put_object(self, bucket: str, key: str, *, expires: timedelta) -> str:
        return f"https://minio/{bucket}/{key}?write={expires.total_seconds():.0f}"

    def remove_object(self, bucket: str, key: str) -> None:
        self._raise_failure()
        self.objects.pop((bucket, key), None)

    def bucket_exists(self, bucket: str) -> bool:
        self._raise_failure()
        assert bucket == "artifacts"
        return self.bucket_present


def _s3_error(code: str, status: int) -> S3Error:
    return S3Error(
        _HttpResponse(status),  # type: ignore[arg-type]
        code,
        code,
        "resource",
        "request-id",
        "host-id",
    )


def _store(client: _FakeMinio, *, timeout_s: float = 1.0) -> MinioObjectStore:
    return MinioObjectStore(
        "unused:9000",
        "access",
        "secret",
        bucket="artifacts",
        operation_timeout_s=timeout_s,
        client=client,
    )


@req("NFR-016")
async def test_put_get_and_delete_round_trip_with_digest_verification() -> None:
    client = _FakeMinio()
    store = _store(client)

    ref = await store.put(
        "artifacts", "workspace/item", b"payload", content_type="text/plain", metadata={"x": "y"}
    )

    assert ref.digest == "sha256:239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5"
    assert client.metadata == {
        "x": "y",
        "agora-sha256": "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
    }
    assert await store.get(ref) == b"payload"
    assert client.response is not None
    assert client.response.closed
    assert client.response.released

    await store.delete(ref)
    assert client.objects == {}
    await store.delete(ref)


@req("NFR-016")
async def test_get_rejects_changed_content() -> None:
    client = _FakeMinio()
    store = _store(client)
    client.objects[("artifacts", "item")] = b"changed"
    ref = ObjectRef(bucket="artifacts", key="item", digest="sha256:expected")

    with pytest.raises(PermanentPortError, match="digest mismatch"):
        await store.get(ref)


@req("NFR-016")
async def test_presign_validates_input_and_checks_read_object() -> None:
    client = _FakeMinio()
    store = _store(client)
    ref = ObjectRef(bucket="artifacts", key="item")

    with pytest.raises(PermanentPortError, match="unsupported"):
        await store.presign(ref, mode="list", ttl_s=10)
    with pytest.raises(PermanentPortError, match="expire"):
        await store.presign(ref, mode="read", ttl_s=0)
    with pytest.raises(NotFoundObjectError):
        await store.presign(ref, mode="read", ttl_s=10)

    assert await store.presign(ref, mode="write", ttl_s=30) == (
        "https://minio/artifacts/item?write=30"
    )
    client.objects[("artifacts", "item")] = b"data"
    assert await store.presign(ref, mode="read", ttl_s=30) == (
        "https://minio/artifacts/item?read=30"
    )


@req("NFR-016")
@pytest.mark.parametrize("code", ["AccessDenied", "InvalidAccessKeyId"])
async def test_permanent_s3_errors_are_translated(code: str) -> None:
    client = _FakeMinio()
    client.failure = _s3_error(code, 403)

    with pytest.raises(PermanentPortError) as raised:
        await _store(client).delete(ObjectRef(bucket="artifacts", key="item"))

    assert raised.value.__cause__ is client.failure


@req("NFR-016")
async def test_service_and_timeout_errors_are_transient() -> None:
    client = _FakeMinio()
    client.failure = _s3_error("SlowDown", 503)
    with pytest.raises(TransientPortError):
        await _store(client).delete(ObjectRef(bucket="artifacts", key="item"))

    client.failure = InvalidResponseError(502, "text/plain", "bad gateway")
    with pytest.raises(TransientPortError, match="protocol fault"):
        await _store(client).delete(ObjectRef(bucket="artifacts", key="item"))

    def slow_bucket_exists(bucket: str) -> bool:
        import time

        time.sleep(0.05)
        return True

    client.failure = None
    client.bucket_exists = slow_bucket_exists  # type: ignore[method-assign]
    with pytest.raises(TransientPortError, match="timed out"):
        await _store(client, timeout_s=0.001)._call(client.bucket_exists, "artifacts")


@req("NFR-016")
async def test_health_distinguishes_missing_bucket_and_dependency_failure() -> None:
    client = _FakeMinio()
    store = _store(client)
    assert await store.health() is HealthStatus.OK

    client.bucket_present = False
    assert await store.health() is HealthStatus.DEGRADED

    client.failure = ConnectionError("offline")
    assert await store.health() is HealthStatus.DOWN
