"""Security tests for workspace-bound provider credential envelope encryption."""

from __future__ import annotations

import base64
from dataclasses import replace
from uuid import uuid4

import pytest

from app.adapters.secrets.envelope import EnvelopeEncryption
from app.adapters.secrets.providers import EnvSecretProvider
from app.ports.errors import PermanentPortError
from app.ports.storage import SecretRef
from tests.traceability import req


@req("NFR-010")
async def test_envelope_round_trip_never_contains_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("llm_master_key", base64.b64encode(b"k" * 32).decode())
    encryption = EnvelopeEncryption(
        EnvSecretProvider(), SecretRef(provider="env_file", name="llm_master_key")
    )
    workspace_id, configuration_id = uuid4(), uuid4()

    envelope = await encryption.encrypt(
        "provider-api-secret", workspace_id=workspace_id, configuration_id=configuration_id
    )

    assert b"provider-api-secret" not in envelope.ciphertext
    assert (
        await encryption.decrypt(
            envelope, workspace_id=workspace_id, configuration_id=configuration_id
        )
        == "provider-api-secret"
    )


@req("NFR-010")
async def test_envelope_rejects_tampering_and_cross_workspace_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("llm_master_key", base64.b64encode(b"m" * 32).decode())
    encryption = EnvelopeEncryption(
        EnvSecretProvider(), SecretRef(provider="env_file", name="llm_master_key")
    )
    workspace_id, configuration_id = uuid4(), uuid4()
    envelope = await encryption.encrypt(
        "secret", workspace_id=workspace_id, configuration_id=configuration_id
    )

    tampered_ciphertext = envelope.ciphertext[:-1] + bytes([envelope.ciphertext[-1] ^ 0x01])
    tampered = replace(envelope, ciphertext=tampered_ciphertext)
    with pytest.raises(PermanentPortError, match="authentication failed"):
        await encryption.decrypt(
            tampered, workspace_id=workspace_id, configuration_id=configuration_id
        )
    with pytest.raises(PermanentPortError, match="authentication failed"):
        await encryption.decrypt(envelope, workspace_id=uuid4(), configuration_id=configuration_id)
