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
# How a container reaches a service on the Docker Desktop host.
CONTAINER_HOST_ALIAS = "host.docker.internal"
EXTRA_FIELD = "extra"


def generate_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


class Answers(BaseModel):
    # Asked: host layout.
    media_host_dir: str | None = None
    timezone: str | None = None

    # Derived: how containers reach host apps.
    jellyfin_host: str = CONTAINER_HOST_ALIAS

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

    # Custom mode: per-target overrides of unbound template keys.
    extra: dict[str, dict[str, str]] = {}

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
            if value is not None and value != {} and not isinstance(value, SecretStr)
        }

    def merged_under(self, other: Answers) -> Answers:
        """This model's decided values, with `other` filling what is still unset."""
        fills = {
            name: getattr(other, name)
            for name in type(self).model_fields
            if name != EXTRA_FIELD and getattr(self, name) is None
        }
        extra = {**other.extra}
        for target, keys in self.extra.items():
            extra[target] = {**extra.get(target, {}), **keys}
        return self.model_copy(update={**fills, EXTRA_FIELD: extra})
