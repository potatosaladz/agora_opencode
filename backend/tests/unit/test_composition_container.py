"""Offline tests for process-scoped adapter composition and lifecycle."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from app.adapters.inmemory.cache import InMemoryCache
from app.adapters.inmemory.event_bus import InMemoryEventBus
from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.inmemory.workflow import InMemoryWorkflowEngine
from app.adapters.z3_symbolic import Z3SymbolicReasoner
from app.composition.container import StartupConfigurationError, build_container
from app.config.settings import Settings
from app.ports.auth import AccessTokenVerificationError
from app.ports.health import ComponentHealth, HealthStatus
from tests.traceability import req


def _settings(**changes: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "event_bus": "inmemory",
        "cache": "inmemory",
        "object_store": "inmemory",
        "secret_provider": "env_file",
    }
    values.update(changes)
    return Settings(**values)


@req("NFR-016")
async def test_builds_offline_adapters_and_exposes_component_health() -> None:
    container = await build_container(_settings())

    assert isinstance(container.event_bus, InMemoryEventBus)
    assert isinstance(container.cache, InMemoryCache)
    assert isinstance(container.object_store, InMemoryObjectStore)
    assert isinstance(container.workflow_engine, InMemoryWorkflowEngine)
    assert isinstance(container.symbolic_reasoner, Z3SymbolicReasoner)
    assert set(container.readiness_checks) == {
        "database",
        "workflow_engine",
        "event_bus",
        "cache",
        "object_store",
        "secret_provider",
    }
    result = await container.readiness_checks["object_store"]()
    assert isinstance(result, ComponentHealth)
    assert result.name == "object_store"
    assert result.status is HealthStatus.OK
    with pytest.raises(AccessTokenVerificationError, match="no access-token verifier"):
        await container.access_token_verifier.verify("any-token")

    await container.close()
    await container.close()
    assert await container.event_bus.health() is HealthStatus.DOWN
    assert await container.workflow_engine.health() is HealthStatus.DOWN


@req("NFR-016")
async def test_close_runs_every_closer_in_reverse_order() -> None:
    calls: list[str] = []

    async def first() -> None:
        calls.append("first")

    async def second() -> None:
        calls.append("second")
        raise RuntimeError("close failed")

    async def third() -> None:
        calls.append("third")

    container = await build_container(_settings())
    container._closers = (first, second, third)

    with pytest.raises(RuntimeError, match="close failed"):
        await container.close()

    assert calls == ["third", "second", "first"]


@req("NFR-016")
@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
async def test_refuses_inmemory_object_store_outside_tests(environment: str) -> None:
    with pytest.raises(StartupConfigurationError, match="allowed only in the test environment"):
        await build_container(_settings(environment=environment))


@req("NFR-016")
async def test_refuses_minio_without_credentials() -> None:
    with pytest.raises(StartupConfigurationError) as caught:
        await build_container(
            _settings(
                object_store="minio",
                minio_access_key=SecretStr(""),
                minio_secret_key=SecretStr(""),
            )
        )

    message = str(caught.value)
    assert "minio_access_key" in message
    assert "minio_secret_key" in message


@req("NFR-016")
async def test_production_policy_is_checked_before_adapter_construction() -> None:
    with pytest.raises(StartupConfigurationError, match="env_file secret provider"):
        await build_container(
            _settings(
                environment="prod",
                object_store="minio",
                minio_access_key=SecretStr("access"),
                minio_secret_key=SecretStr("secret"),
            )
        )


@req("NFR-016")
async def test_selected_minio_adapter_receives_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeMinio(InMemoryObjectStore):
        def __init__(
            self,
            endpoint: str,
            access_key: str,
            secret_key: str,
            *,
            secure: bool,
            bucket: str,
        ) -> None:
            super().__init__()
            captured.update(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
                bucket=bucket,
            )

    monkeypatch.setattr("app.composition.container.MinioObjectStore", FakeMinio)
    container = await build_container(
        _settings(
            object_store="minio",
            minio_endpoint="objects.internal:9443",
            minio_access_key=SecretStr("access"),
            minio_secret_key=SecretStr("secret"),
            minio_secure=True,
            minio_bucket="artifacts",
        )
    )

    assert captured == {
        "endpoint": "objects.internal:9443",
        "access_key": "access",
        "secret_key": "secret",
        "secure": True,
        "bucket": "artifacts",
    }
    await container.close()


@req("NFR-016")
async def test_nats_is_connected_eagerly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeNats(InMemoryEventBus):
        def __init__(self, url: str, *, stream: str) -> None:
            super().__init__()
            calls.extend((url, stream))

        async def connect(self) -> None:
            calls.append("connect")

    monkeypatch.setattr("app.composition.container.NatsJetStreamEventBus", FakeNats)
    container = await build_container(_settings(event_bus="nats", nats_url="nats://bus:4222"))

    assert calls == ["nats://bus:4222", "AGORA", "connect"]
    await container.close()


@req("NFR-016")
async def test_selected_temporal_adapter_receives_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeTemporal(InMemoryWorkflowEngine):
        @classmethod
        async def connect(
            cls,
            address: str,
            *,
            namespace: str,
            connect_timeout_s: float,
            health_timeout_s: float,
        ) -> FakeTemporal:
            captured.update(
                address=address,
                namespace=namespace,
                connect_timeout_s=connect_timeout_s,
                health_timeout_s=health_timeout_s,
            )
            return cls()

    monkeypatch.setattr("app.composition.container.TemporalWorkflowEngine", FakeTemporal)
    container = await build_container(
        _settings(
            workflow_engine="temporal",
            temporal_address="workflow.internal:7233",
            temporal_namespace="agora-test",
            temporal_connect_timeout_s=4.0,
            temporal_health_timeout_s=2.0,
        )
    )

    assert captured == {
        "address": "workflow.internal:7233",
        "namespace": "agora-test",
        "connect_timeout_s": 4.0,
        "health_timeout_s": 2.0,
    }
    await container.close()
