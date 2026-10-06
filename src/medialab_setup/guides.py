"""Where each asked credential comes from: the console URL, the click path, the shape.

Text follows the credential table in the workspace's `docs/secrets.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Check(str, Enum):
    """Which live, read-only validation applies to a credential."""

    TMDB = "tmdb"
    JELLYFIN = "jellyfin"
    DISCORD = "discord"


@dataclass(frozen=True)
class Guide:
    field: str
    title: str
    url: str | None
    steps: tuple[str, ...]
    looks_like: str
    check: Check | None = None
    secret: bool = True


GUIDES: tuple[Guide, ...] = (
    Guide(
        field="media_host_dir",
        title="Media root folder",
        url=None,
        steps=(
            "A folder on a drive with room for your library, for example F:/Media.",
            "Movies, Shows and the _incoming staging folders are created inside it.",
            "Never add _incoming as a Jellyfin library.",
        ),
        looks_like="F:/Media",
        secret=False,
    ),
    Guide(
        field="timezone",
        title="Timezone for container logs",
        url="https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
        steps=("An IANA zone name such as America/Toronto.",),
        looks_like="America/Toronto",
        secret=False,
    ),
    Guide(
        field="tmdb_api_key",
        title="TMDB API key (v3)",
        url="https://www.themoviedb.org/settings/api",
        steps=(
            "Sign in to themoviedb.org, open Settings, then API.",
            "Request a v3 developer key; the application can be described as personal use.",
            "Copy the value labelled API Key (v3 auth), not the Read Access Token.",
        ),
        looks_like="32 hexadecimal characters",
        check=Check.TMDB,
    ),
    Guide(
        field="jellyfin_api_key",
        title="Jellyfin API key",
        url="http://127.0.0.1:8096/web/#/dashboard/keys",
        steps=(
            "Open the Jellyfin dashboard on this machine, Administration, then API Keys.",
            "Add a key named medialab and copy it.",
        ),
        looks_like="32 hexadecimal characters",
        check=Check.JELLYFIN,
    ),
    Guide(
        field="discord_token",
        title="Discord bot token",
        url="https://discord.com/developers/applications",
        steps=(
            "Create an application, open its Bot page, and reset the token to reveal it.",
            "Under Privileged Gateway Intents nothing extra is needed for slash commands.",
            "Invite the bot to your server with the applications.commands and bot scopes.",
        ),
        looks_like="three dot-separated base64 groups",
        check=Check.DISCORD,
    ),
    Guide(
        field="discord_guild_id",
        title="Discord server id",
        url="https://support.discord.com/hc/en-us/articles/206346498",
        steps=(
            "Enable Developer Mode in Discord's Advanced settings.",
            "Right-click your server name and choose Copy Server ID.",
        ),
        looks_like="17 to 20 digits",
        secret=False,
    ),
    Guide(
        field="discord_notify_webhook_url",
        title="Discord notification webhook (optional)",
        url="https://support.discord.com/hc/en-us/articles/228383668",
        steps=(
            "In the target channel: Edit Channel, Integrations, Webhooks, New Webhook.",
            "Copy the webhook URL. Anyone holding it can post to the channel.",
            "Leave empty to skip completion notifications.",
        ),
        looks_like="https://discord.com/api/webhooks/...",
    ),
    Guide(
        field="web_password",
        title="Web UI password",
        url=None,
        steps=("Choose a strong password for the browser UI; the cookie secret is generated.",),
        looks_like="any strong passphrase",
    ),
    Guide(
        field="vpn_service_provider",
        title="VPN provider (gluetun name)",
        url="https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers",
        steps=("The gluetun provider name, for example nordvpn, mullvad, protonvpn.",),
        looks_like="nordvpn",
        secret=False,
    ),
    Guide(
        field="vpn_type",
        title="VPN protocol",
        url=None,
        steps=("wireguard unless the provider only offers openvpn.",),
        looks_like="wireguard",
        secret=False,
    ),
    Guide(
        field="wireguard_private_key",
        title="WireGuard private key",
        url="https://my.nordaccount.com/dashboard/nordvpn/manual-configuration/",
        steps=(
            "NordVPN: account site, NordVPN, Manual setup, generate an access token.",
            "Run: curl -s -u token:TOKEN https://api.nordvpn.com/v1/users/services/credentials",
            "Copy nordlynx_private_key from the response.",
            "Other providers issue the key on their WireGuard configuration page.",
            "No VPN account password is ever collected.",
        ),
        looks_like="44 base64 characters ending in =",
    ),
    Guide(
        field="server_countries",
        title="VPN exit country",
        url=None,
        steps=("A country gluetun knows for your provider, for example Canada.",),
        looks_like="Canada",
        secret=False,
    ),
)


def guide_for(field: str) -> Guide:
    for guide in GUIDES:
        if guide.field == field:
            return guide
    raise KeyError(field)
