"""SecretsAdapter — secret material retrieval interface.

Resolves named secrets (API keys, connector credentials) at runtime. Secret
*names* — never their values — appear in configuration (e.g.
``HRIS_API_KEY_SECRET=hris-api-key``). Concrete targets back this with GCP
Secret Manager, AWS Secrets Manager, or a local JSON file for development.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SecretNotFoundError(KeyError):
    """Raised when a requested secret name does not exist."""


class SecretsAdapter(ABC):
    """Read access to named secrets."""

    @abstractmethod
    async def get_secret(self, name: str) -> str:
        """Return the secret value for ``name``.

        Raises :class:`SecretNotFoundError` if no such secret exists.
        """
        ...

    @abstractmethod
    async def exists(self, name: str) -> bool:
        """Return whether a secret named ``name`` is available."""
        ...
