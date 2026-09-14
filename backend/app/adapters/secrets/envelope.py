"""AES-GCM envelope encryption with a master key resolved through ``SecretProvider``."""

from __future__ import annotations

import base64
import binascii
import os
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.domain.agent_registry import CredentialEnvelope
from app.ports.errors import PermanentPortError
from app.ports.storage import SecretProvider, SecretRef

__all__ = ["EnvelopeEncryption"]

_ALGORITHM = "AES-256-GCM"
_KEY_BYTES = 32
_NONCE_BYTES = 12


class EnvelopeEncryption:
    """Encrypt each credential with a random key, then wrap it with an external master key."""

    def __init__(self, secret_provider: SecretProvider, master_key_ref: SecretRef) -> None:
        self._secret_provider = secret_provider
        self._master_key_ref = master_key_ref

    async def encrypt(
        self, plaintext: str, *, workspace_id: UUID, configuration_id: UUID
    ) -> CredentialEnvelope:
        if not plaintext:
            raise PermanentPortError("credential must not be empty", port="credential_encryption")
        master_key = await self._master_key()
        data_key = os.urandom(_KEY_BYTES)
        credential_nonce = os.urandom(_NONCE_BYTES)
        wrapping_nonce = os.urandom(_NONCE_BYTES)
        aad = _aad(workspace_id, configuration_id)
        ciphertext = AESGCM(data_key).encrypt(credential_nonce, plaintext.encode(), aad)
        wrapped_data_key = AESGCM(master_key).encrypt(wrapping_nonce, data_key, aad)
        return CredentialEnvelope(
            ciphertext=ciphertext,
            credential_nonce=credential_nonce,
            wrapped_data_key=wrapped_data_key,
            wrapping_nonce=wrapping_nonce,
            master_key_ref=self._master_key_ref,
        )

    async def decrypt(
        self, envelope: CredentialEnvelope, *, workspace_id: UUID, configuration_id: UUID
    ) -> str:
        if envelope.algorithm != _ALGORITHM:
            raise PermanentPortError(
                f"unsupported credential envelope algorithm {envelope.algorithm!r}",
                port="credential_encryption",
            )
        master_key = await self._master_key()
        aad = _aad(workspace_id, configuration_id)
        try:
            data_key = AESGCM(master_key).decrypt(
                envelope.wrapping_nonce, envelope.wrapped_data_key, aad
            )
            plaintext = AESGCM(data_key).decrypt(
                envelope.credential_nonce, envelope.ciphertext, aad
            )
            return plaintext.decode()
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise PermanentPortError(
                "credential envelope authentication failed", port="credential_encryption"
            ) from exc

    async def _master_key(self) -> bytes:
        encoded = await self._secret_provider.resolve(self._master_key_ref)
        try:
            key = base64.b64decode(encoded, altchars=b"-_", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PermanentPortError(
                "credential master key must be base64-encoded", port="credential_encryption"
            ) from exc
        if len(key) != _KEY_BYTES:
            raise PermanentPortError(
                "credential master key must decode to 32 bytes", port="credential_encryption"
            )
        return key


def _aad(workspace_id: UUID, configuration_id: UUID) -> bytes:
    return f"agora:llm-credential:v1:{workspace_id}:{configuration_id}".encode()
