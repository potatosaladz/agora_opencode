"""Layered configuration. `memory-bank/techContext.md` §4.

Precedence, lowest to highest: field defaults -> `.env` (dev only) -> Docker Swarm
secrets mounted under `/run/secrets` -> process environment.

Two rules are enforced here rather than documented and hoped for:

* **No secret literals.** Every credential field is a `SecretStr`, and
  `tests/test_config.py` asserts that no field name matching a secret pattern has a
  non-empty default.
* **Adapters are named, not configured inline.** `event_bus=...`, `vector_store=...` etc.
  select an implementation in `app/composition`, so a test can run the whole application
  against in-memory adapters without monkeypatching (techContext §4: "tests must run fully
  offline").
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]

#: Where Swarm mounts secrets. Read only when it exists, so dev machines never need it.
SECRETS_PATH = Path("/run/secrets")

Environment = Literal["test", "dev", "staging", "prod"]


class Settings(BaseSettings):
    """Runtime configuration for every deployment role in `backend/app`."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- identity and environment ------------------------------------------------
    environment: Environment = "dev"
    service_name: str = "api"
    code_version: str = "dev"

    # -- http --------------------------------------------------------------------
    host: str = "0.0.0.0"  # Containers need the wildcard; TLS terminates at the proxy.
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # -- adapter selection (techContext.md §4) -----------------------------------
    event_bus: Literal["nats", "inmemory"] = "inmemory"
    vector_store: Literal["pgvector"] = "pgvector"
    object_store: Literal["minio", "inmemory"] = "minio"
    cache: Literal["redis", "inmemory"] = "redis"
    secret_provider: Literal["env_file", "swarm_secret"] = "env_file"
    workflow_engine: Literal["temporal", "inmemory"] = "inmemory"  # D-11
    llm_provider: Literal["openai_compatible", "mock"] = "mock"  # Phase 2
    symbolic_reasoner: Literal["z3"] = "z3"  # Phase 11
    symbolic_timeout_ms: int = Field(default=5_000, ge=1, le=60_000)

    # -- postgres ------------------------------------------------------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "agora"
    postgres_user: str = "agora"
    postgres_password: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_statement_timeout_ms: int = 15_000

    # -- nats ----------------------------------------------------------------------
    nats_url: str = "nats://nats:4222"
    nats_stream: str = "AGORA"

    # -- temporal ------------------------------------------------------------------
    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_connect_timeout_s: float = Field(default=5.0, gt=0)
    temporal_health_timeout_s: float = Field(default=3.0, gt=0)
    temporal_start_timeout_s: float = Field(default=5.0, gt=0)
    temporal_signal_timeout_s: float = Field(default=5.0, gt=0)
    temporal_task_queue: str = Field(default="session-bootstrap", min_length=1)
    workflow_service_actor_id: UUID = UUID("018f0000-0000-7000-8000-000000000000")

    # -- redis ---------------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"

    # -- minio -----------------------------------------------------------------------
    minio_endpoint: str = "minio:9000"
    minio_access_key: SecretStr = SecretStr("")
    minio_secret_key: SecretStr = SecretStr("")
    minio_secure: bool = False
    minio_bucket: str = "agora-artifacts"

    # -- observability ----------------------------------------------------------------
    otel_exporter_endpoint: str = ""
    otel_service_name: str = "agora-api"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    metrics_enabled: bool = True

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    @property
    def is_prod(self) -> bool:
        return self.environment in ("staging", "prod")

    @property
    def sqlalchemy_url(self) -> str:
        """Async DSN. The password is decoded only at the moment of interpolation."""
        auth = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{auth}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def swarm_secret(self, name: str) -> str | None:
        """Read a Swarm-mounted secret, or None if this host has no secrets directory.

        ADR-017: production reads credentials from mounted files, never from the
        environment, so they never appear in `docker inspect` or a shell history.
        """
        candidate = SECRETS_PATH / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
        return None

    def startup_problems(self) -> list[str]:
        """Configuration that must not ship to production. Checked at startup, not per request."""
        problems: list[str] = []
        if self.is_prod:
            if self.secret_provider != "swarm_secret":
                problems.append("prod must not use the env_file secret provider (ADR-017)")
            if self.log_format != "json":
                problems.append("prod logs must be structured json")
            if self.postgres_password.get_secret_value() == "":
                problems.append("postgres_password is empty")
        return problems


@lru_cache
def get_settings() -> Settings:
    """Cached settings. Reading `.env` per request would be slow and also a lie:
    configuration is fixed for the life of a process."""
    return Settings()
