"""MinIO acceptance proof for upload, presigned read, integrity, and list denial."""

from __future__ import annotations

import json
import os
from io import BytesIO

import httpx
import pytest
from minio import Minio
from minio.error import S3Error

from app.adapters.minio.object_store import MinioObjectStore
from app.ports.errors import PermanentPortError
from app.ports.health import HealthStatus
from tests.traceability import req

_ENDPOINT = os.getenv("TEST_MINIO_ENDPOINT")
_ACCESS_KEY = os.getenv("TEST_MINIO_ACCESS_KEY")
_SECRET_KEY = os.getenv("TEST_MINIO_SECRET_KEY")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all((_ENDPOINT, _ACCESS_KEY, _SECRET_KEY)),
        reason="TEST_MINIO_ENDPOINT and credentials are not configured",
    ),
]
_BUCKET = "agora-t107-artifacts"


@req("NFR-016")
async def test_minio_round_trip_presign_digest_and_list_denial() -> None:
    assert _ENDPOINT is not None
    assert _ACCESS_KEY is not None
    assert _SECRET_KEY is not None
    admin = Minio(_ENDPOINT, access_key=_ACCESS_KEY, secret_key=_SECRET_KEY, secure=False)
    if admin.bucket_exists(_BUCKET):
        for item in admin.list_objects(_BUCKET, recursive=True):
            admin.remove_object(_BUCKET, item.object_name)
        admin.remove_bucket(_BUCKET)
    admin.make_bucket(_BUCKET)
    admin.set_bucket_policy(
        _BUCKET,
        json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Deny",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:ListBucket"],
                        "Resource": [f"arn:aws:s3:::{_BUCKET}"],
                    }
                ],
            }
        ),
    )
    store = MinioObjectStore(
        _ENDPOINT,
        _ACCESS_KEY,
        _SECRET_KEY,
        bucket=_BUCKET,
    )

    ref = await store.put(
        _BUCKET,
        "workspace-a/proof.txt",
        b"verified payload",
        content_type="text/plain",
        metadata={"workspace": "a"},
    )
    assert ref.digest.startswith("sha256:")
    assert await store.get(ref) == b"verified payload"
    assert await store.health() is HealthStatus.OK

    url = await store.presign(ref, mode="read", ttl_s=60)
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    assert response.status_code == 200
    assert response.content == b"verified payload"

    anonymous = Minio(_ENDPOINT, secure=False)
    with pytest.raises(S3Error, match="Access Denied") as denied:
        list(anonymous.list_objects(_BUCKET, recursive=True))
    assert denied.value.code == "AccessDenied"

    admin.put_object(
        _BUCKET,
        ref.key,
        BytesIO(b"tampered"),
        len(b"tampered"),
        content_type="text/plain",
    )
    with pytest.raises(PermanentPortError, match="digest mismatch"):
        await store.get(ref)

    admin.remove_object(_BUCKET, ref.key)
    admin.remove_bucket(_BUCKET)
    await store.close()
