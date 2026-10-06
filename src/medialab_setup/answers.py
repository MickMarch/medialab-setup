"""Every value the operator decides, or the tool decides for them, in one model.

Fields are optional so the model can be built up from several sources
(existing `.env` files, an answers file, prompts). A `None` means "not
decided": the renderer then keeps the existing or template value. Secret
fields are `SecretStr` so no dump or repr can leak them.
"""

from __future__ import annotations

import secrets
from typing import Any

from pydantic import BaseModel, SecretStr

from medialab_setup.bindings import GENERATED_FIELDS

SECRET_BYTES = 32


def generate_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


class Answers(BaseModel):
    # Asked: host layout.
    media_host_dir: str | None = None
    timezone: str | None = None

    # Asked: third-party credentials.
    tmdb_api_key: SecretStr | None = None
    jellyfin_api_key: SecretStr | None = None
    discord_token: SecretStr | None = None
    discord_guild_id: str | None = None
    discord_notify_webhook_url: SecretStr | None = None
    web_password: SecretStr | None = None

    # Asked: VPN provider block.
    vpn_service_provider: str | None = None
    vpn_type: str | None = None
    wireguard_private_key: SecretStr | None = None
    server_countries: str | None = None

    # Generated: never asked.
    orchestrator_api_key: SecretStr | None = None
    downloader_api_key: SecretStr | None = None
    jellyfin_worker_api_key: SecretStr | None = None
    qb_api_key: SecretStr | None = None
    web_secret_key: SecretStr | None = None

    def with_generated(self) -> Answers:
        """Fill every generated field that is still unset."""
        fills = {
            field: SecretStr(generate_secret())
            for field in GENERATED_FIELDS
            if getattr(self, field) is None
        }
        return self.model_copy(update=fills)

    def plain_value(self, field: str) -> str | None:
        value = getattr(self, field)
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        return value

    def redacted_dump(self) -> dict[str, Any]:
        """Non-secret, decided values only; what the answers file may hold."""
        return {
            name: value
            for name, value in self.model_dump().items()
            if value is not None and not isinstance(value, SecretStr)
        }
