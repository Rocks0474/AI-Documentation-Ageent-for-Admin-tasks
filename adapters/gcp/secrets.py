"""GCP SecretsAdapter — Secret Manager.

Resolves the latest enabled version of a named secret. Secret *names* come from
configuration (e.g. ``HRIS_API_KEY_SECRET=hris-api-key``); values live only in
Secret Manager.
"""

from __future__ import annotations

import asyncio
import os

from adapters.base.secrets import SecretNotFoundError, SecretsAdapter


def _is_not_found(exc: Exception) -> bool:
    # Avoid importing google.api_core.exceptions so this module stays importable
    # without the SDK; match on the exception class name instead.
    return type(exc).__name__ in {"NotFound", "PermissionDenied", "FailedPrecondition"}


class GCPSecretsAdapter(SecretsAdapter):
    def __init__(self, client, project_id: str) -> None:
        self._client = client
        self._project_id = project_id

    def _version_name(self, name: str) -> str:
        return f"projects/{self._project_id}/secrets/{name}/versions/latest"

    async def get_secret(self, name: str) -> str:
        def _access() -> str:
            response = self._client.access_secret_version(
                name=self._version_name(name)
            )
            return response.payload.data.decode("utf-8")

        try:
            return await asyncio.to_thread(_access)
        except Exception as exc:  # noqa: BLE001 - re-raised as typed error below
            if _is_not_found(exc):
                raise SecretNotFoundError(name) from exc
            raise

    async def exists(self, name: str) -> bool:
        try:
            await self.get_secret(name)
        except SecretNotFoundError:
            return False
        return True


def get_adapter() -> GCPSecretsAdapter:
    from google.cloud import secretmanager  # lazy import

    client = secretmanager.SecretManagerServiceClient()
    project_id = os.environ["GCP_PROJECT_ID"]
    return GCPSecretsAdapter(client, project_id)
