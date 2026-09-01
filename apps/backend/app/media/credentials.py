from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.federation import EndpointCipher
from app.models import CredentialProfile


class CredentialResolutionUnavailable(Exception):
    """Raised without embedding the credential reference or secret material."""


@dataclass(slots=True)
class CredentialLease:
    """Short-lived plaintext material held only inside an assigned worker boundary.

    Secrets are never returned through an API schema. ``authenticated_uri`` is
    used only after the non-secret endpoint has passed adapter/network policy;
    the runtime sends it through protected stdin, never process arguments.
    """

    username: str = field(repr=False)
    password: str = field(repr=False)
    source: str
    profile_id: str | None = None

    def authenticated_uri(self, endpoint: str) -> str:
        parsed = urlsplit(endpoint)
        if parsed.username is not None or parsed.password is not None or not parsed.hostname:
            raise CredentialResolutionUnavailable("The media endpoint cannot accept credentials")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        userinfo = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}"
        return urlunsplit(
            (parsed.scheme, f"{userinfo}@{host}", parsed.path, parsed.query, parsed.fragment)
        )

    def close(self) -> None:
        self.username = ""
        self.password = ""


class CredentialResolver(Protocol):
    mode: str

    def resolve(self, reference: str) -> CredentialLease: ...


class FailClosedCredentialResolver:
    mode = "fail_closed"

    def resolve(self, reference: str) -> CredentialLease:
        del reference
        raise CredentialResolutionUnavailable("Credential-backed runtime handoff is not configured")


class DatabaseCredentialResolver:
    """Resolve only local encrypted ``credential-profile:<uuid>`` references.

    External Vault/KMS references remain fail-closed until a workload-identity
    provider is configured. Department matching prevents a profile from being
    reused across administrative ownership boundaries.
    """

    mode = "encrypted_database_profiles"

    def __init__(
        self,
        session: Session,
        *,
        cipher: EndpointCipher,
        department_id: str,
    ) -> None:
        self.session = session
        self.cipher = cipher
        self.department_id = department_id

    def resolve(self, reference: str) -> CredentialLease:
        prefix = "credential-profile:"
        if not reference.startswith(prefix):
            raise CredentialResolutionUnavailable(
                "This runtime node does not resolve external credential references"
            )
        profile_id = reference.removeprefix(prefix)
        profile = self.session.get(CredentialProfile, profile_id)
        if not profile or not profile.enabled or profile.department_id != self.department_id:
            raise CredentialResolutionUnavailable(
                "The credential profile is unavailable for this camera"
            )
        profile.last_used_at = datetime.now(UTC)
        return CredentialLease(
            username=self.cipher.decrypt(profile.username_ciphertext),
            password=self.cipher.decrypt(profile.secret_ciphertext),
            source=prefix.rstrip(":"),
            profile_id=profile.id,
        )
