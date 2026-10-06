"""Which `.env` key in which file carries which answer.

This is the one place that knows a service's key names. A field bound to two
places is a pair from the key-pair table in `docs/secrets.md`; the renderer
writes the same value to both so they cannot drift. The first binding of a
field is its owner: when an existing `.env` already holds a value, the owner's
copy is the one that is kept.
"""

from __future__ import annotations

from dataclasses import dataclass

from medialab_setup.workspace import GLUETUN_TARGET, ROOT_TARGET

DOWNLOADER = "torrent-downloader"
JELLYFIN_WORKER = "medialab-jellyfin"
ORCHESTRATOR = "medialab-orchestrator"
BOT = "medialab-bot"
WEB = "medialab-web"


@dataclass(frozen=True)
class Binding:
    target: str
    key: str
    field: str


BINDINGS: tuple[Binding, ...] = (
    Binding(ROOT_TARGET, "MEDIA_HOST_DIR", "media_host_dir"),
    Binding(ROOT_TARGET, "TZ", "timezone"),
    # Owners first, then the callers that must match them.
    Binding(ORCHESTRATOR, "API_KEY", "orchestrator_api_key"),
    Binding(BOT, "ORCHESTRATOR_API_KEY", "orchestrator_api_key"),
    Binding(WEB, "ORCHESTRATOR_API_KEY", "orchestrator_api_key"),
    Binding(DOWNLOADER, "API_KEY", "downloader_api_key"),
    Binding(ORCHESTRATOR, "TORRENT_DOWNLOADER_API_KEY", "downloader_api_key"),
    Binding(JELLYFIN_WORKER, "API_KEY", "jellyfin_worker_api_key"),
    Binding(ORCHESTRATOR, "MEDIALAB_JELLYFIN_API_KEY", "jellyfin_worker_api_key"),
    Binding(DOWNLOADER, "QB_API_KEY", "qb_api_key"),
    Binding(DOWNLOADER, "TMDB_API_KEY", "tmdb_api_key"),
    Binding(JELLYFIN_WORKER, "JELLYFIN_API_KEY", "jellyfin_api_key"),
    Binding(BOT, "DISCORD_TOKEN", "discord_token"),
    Binding(BOT, "DISCORD_GUILD_ID", "discord_guild_id"),
    Binding(ORCHESTRATOR, "DISCORD_NOTIFY_WEBHOOK_URL", "discord_notify_webhook_url"),
    Binding(WEB, "WEB_PASSWORD", "web_password"),
    Binding(WEB, "WEB_SECRET_KEY", "web_secret_key"),
    Binding(GLUETUN_TARGET, "VPN_SERVICE_PROVIDER", "vpn_service_provider"),
    Binding(GLUETUN_TARGET, "VPN_TYPE", "vpn_type"),
    Binding(GLUETUN_TARGET, "WIREGUARD_PRIVATE_KEY", "wireguard_private_key"),
    Binding(GLUETUN_TARGET, "SERVER_COUNTRIES", "server_countries"),
)

# Caller (target, key) must equal callee (target, key): the table in docs/secrets.md.
KEY_PAIRS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    ((BOT, "ORCHESTRATOR_API_KEY"), (ORCHESTRATOR, "API_KEY")),
    ((WEB, "ORCHESTRATOR_API_KEY"), (ORCHESTRATOR, "API_KEY")),
    ((ORCHESTRATOR, "TORRENT_DOWNLOADER_API_KEY"), (DOWNLOADER, "API_KEY")),
    ((ORCHESTRATOR, "MEDIALAB_JELLYFIN_API_KEY"), (JELLYFIN_WORKER, "API_KEY")),
)

GENERATED_FIELDS: tuple[str, ...] = (
    "orchestrator_api_key",
    "downloader_api_key",
    "jellyfin_worker_api_key",
    "qb_api_key",
    "web_secret_key",
)


def owner_of(field: str, bindings: tuple[Binding, ...] = BINDINGS) -> Binding | None:
    for binding in bindings:
        if binding.field == field:
            return binding
    return None
