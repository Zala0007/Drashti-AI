from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.errors import BadRequestError, RegistryError


def load_or_create_development_key(path_value: str) -> str:
    """Persist a local-only Fernet key with owner-restricted permissions.

    Production never calls this path. It exists so a zero-Docker development
    portal can keep encrypted connection profiles readable across restarts
    without checking a key into source control.
    """

    path = Path(path_value).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            value = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError("The local development encryption key could not be read") from exc
    else:
        value = Fernet.generate_key().decode("ascii")
        try:
            with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
                handle.write(value)
                handle.write("\n")
            try:
                path.chmod(0o600)
            except OSError:
                pass
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
    EndpointCipher(value, key_id="development-key-validation")
    return value


class EndpointCipher:
    """Fernet encryption plus a domain-separated keyed endpoint fingerprint."""

    def __init__(self, key: str | None, *, key_id: str) -> None:
        if not key_id.strip() or len(key_id) > 120:
            raise ValueError("FEDERATION_ENCRYPTION_KEY_ID must contain 1-120 characters")
        self.key_id = key_id.strip()
        self._fernet: Fernet | None = None
        self._fingerprint_key: bytes | None = None
        if key:
            try:
                raw_key = base64.urlsafe_b64decode(key.encode("ascii"))
                if len(raw_key) != 32:
                    raise ValueError
                self._fernet = Fernet(key.encode("ascii"))
            except (binascii.Error, ValueError, TypeError, UnicodeError) as exc:
                raise ValueError("FEDERATION_ENCRYPTION_KEY must be a valid Fernet key") from exc
            self._fingerprint_key = hmac.new(
                raw_key,
                b"drishti-ai/federation/endpoint-fingerprint/v1",
                hashlib.sha256,
            ).digest()

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def _require(self) -> tuple[Fernet, bytes]:
        if not self._fernet or not self._fingerprint_key:
            raise RegistryError(
                code="FEDERATION_ENCRYPTION_UNAVAILABLE",
                message="Federation endpoint encryption is not configured",
                status_code=503,
            )
        return self._fernet, self._fingerprint_key

    def encrypt(self, endpoint: str) -> str:
        fernet, _ = self._require()
        return fernet.encrypt(endpoint.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        fernet, _ = self._require()
        try:
            return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise RegistryError(
                code="FEDERATION_ENDPOINT_DECRYPTION_FAILED",
                message="The stored connection endpoint cannot be decrypted with the active key",
                status_code=503,
            ) from exc

    def fingerprint(self, endpoint: str) -> str:
        _, fingerprint_key = self._require()
        return hmac.new(fingerprint_key, endpoint.encode("utf-8"), hashlib.sha256).hexdigest()


def validate_credential_reference(value: str | None) -> str | None:
    """Accept only opaque resolver identifiers, never credentials or URLs."""

    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    allowed_prefixes = ("credential-profile:", "vault-ref:", "kms-ref:")
    if not value.startswith(allowed_prefixes):
        raise BadRequestError(
            "INVALID_CREDENTIAL_REFERENCE",
            "credential_reference must be an opaque credential-profile, "
            "vault-ref or kms-ref identifier",
        )
    suffix = value.split(":", 1)[1]
    safe_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
    if not suffix or len(value) > 500 or any(char not in safe_characters for char in suffix):
        raise BadRequestError(
            "INVALID_CREDENTIAL_REFERENCE",
            "credential_reference contains unsupported characters",
        )
    return value
