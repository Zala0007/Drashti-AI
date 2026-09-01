from __future__ import annotations

from typing import Any


class RegistryError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class NotFoundError(RegistryError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            code=f"{resource.upper()}_NOT_FOUND",
            message=f"{resource.replace('_', ' ').title()} was not found",
            status_code=404,
            details={"identifier": identifier},
        )


class ConflictError(RegistryError):
    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(code=code, message=message, status_code=409, details=details)


class BadRequestError(RegistryError):
    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(code=code, message=message, status_code=400, details=details)
