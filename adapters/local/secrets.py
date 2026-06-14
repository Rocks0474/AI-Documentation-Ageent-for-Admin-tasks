"""LOCAL SecretsAdapter — reads from a local JSON file, with env fallback.

Secrets are read from ``LOCAL_SECRETS_FILE`` (default ``./secrets.local.json``),
a flat ``{name: value}`` map. If a name is absent there, the process environment
is consulted (useful for ``ANTHROPIC_API_KEY`` during local development).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from adapters.base.secrets import SecretNotFoundError, SecretsAdapter


class LocalSecretsAdapter(SecretsAdapter):
    def __init__(self, path: Optional[str] = None) -> None:
        self._path = Path(
            path or os.environ.get("LOCAL_SECRETS_FILE", "./secrets.local.json")
        )

    def _load(self) -> dict[str, str]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def get_secret(self, name: str) -> str:
        data = self._load()
        if name in data:
            return str(data[name])
        env_value = os.environ.get(name)
        if env_value is not None:
            return env_value
        raise SecretNotFoundError(name)

    async def exists(self, name: str) -> bool:
        return name in self._load() or name in os.environ


_adapter: Optional[LocalSecretsAdapter] = None


def get_adapter() -> LocalSecretsAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LocalSecretsAdapter()
    return _adapter
