"""AWS SecretsAdapter — AWS Secrets Manager."""

from __future__ import annotations

import asyncio
import os

from adapters.aws._errors import is_not_found
from adapters.base.secrets import SecretNotFoundError, SecretsAdapter


class AWSSecretsAdapter(SecretsAdapter):
    def __init__(self, client) -> None:
        self._client = client

    async def get_secret(self, name: str) -> str:
        def _get() -> str:
            try:
                response = self._client.get_secret_value(SecretId=name)
            except Exception as exc:  # noqa: BLE001 - mapped to typed error
                if is_not_found(exc):
                    raise SecretNotFoundError(name) from exc
                raise
            if "SecretString" in response:
                return response["SecretString"]
            return response["SecretBinary"].decode("utf-8")

        return await asyncio.to_thread(_get)

    async def exists(self, name: str) -> bool:
        try:
            await self.get_secret(name)
        except SecretNotFoundError:
            return False
        return True


def get_adapter() -> AWSSecretsAdapter:
    import boto3  # lazy import

    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client("secretsmanager", region_name=region)
    return AWSSecretsAdapter(client)
