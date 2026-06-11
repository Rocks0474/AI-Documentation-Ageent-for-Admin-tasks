"""Helpers for interpreting boto3/botocore errors without importing botocore.

botocore raises ``ClientError`` with ``exc.response['Error']['Code']``. We read
that defensively so these modules stay importable without the SDK installed.
"""

from __future__ import annotations

from typing import Optional

_NOT_FOUND_CODES = frozenset(
    {
        "NoSuchKey",
        "NoSuchBucket",
        "404",
        "NotFound",
        "ResourceNotFoundException",
    }
)

_CONFLICT_CODES = frozenset({"ConflictException", "ResourceAlreadyExistsException"})


def error_code(exc: Exception) -> Optional[str]:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code")
    return None


def is_not_found(exc: Exception) -> bool:
    return error_code(exc) in _NOT_FOUND_CODES


def is_conflict(exc: Exception) -> bool:
    return error_code(exc) in _CONFLICT_CODES
