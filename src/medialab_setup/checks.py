"""Live, read-only credential checks. Mocked at this class boundary in tests."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

import httpx

from medialab_setup.guides import Check

REQUEST_TIMEOUT_SECONDS = 8.0
TMDB_CONFIGURATION_URL = "https://api.themoviedb.org/3/configuration"
TMDB_KEY_PARAM = "api_key"
JELLYFIN_SYSTEM_INFO_PATH = "/System/Info"
JELLYFIN_TOKEN_HEADER = "X-Emby-Token"
DISCORD_ME_URL = "https://discord.com/api/v10/users/@me"
DISCORD_AUTH_SCHEME = "Bot"
DEFAULT_JELLYFIN_URL = "http://127.0.0.1:8096"


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str
    unverified: bool = False

    @classmethod
    def offline(cls, error: Exception) -> CheckResult:
        detail = f"could not reach the service ({error}); unverified"
        return cls(ok=True, detail=detail, unverified=True)


class CredentialChecker:
    def __init__(self, jellyfin_url: str = DEFAULT_JELLYFIN_URL) -> None:
        self.jellyfin_url = jellyfin_url.rstrip("/")

    def run(self, check: Check, value: str) -> CheckResult:
        try:
            if check is Check.TMDB:
                return self._status_check(
                    httpx.get(
                        TMDB_CONFIGURATION_URL,
                        params={TMDB_KEY_PARAM: value},
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    ),
                    "TMDB accepted the key",
                    "TMDB rejected the key",
                )
            if check is Check.JELLYFIN:
                return self._status_check(
                    httpx.get(
                        f"{self.jellyfin_url}{JELLYFIN_SYSTEM_INFO_PATH}",
                        headers={JELLYFIN_TOKEN_HEADER: value},
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    ),
                    "Jellyfin accepted the key",
                    "Jellyfin rejected the key",
                )
            return self._status_check(
                httpx.get(
                    DISCORD_ME_URL,
                    headers={"Authorization": f"{DISCORD_AUTH_SCHEME} {value}"},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                ),
                "Discord accepted the token",
                "Discord rejected the token",
            )
        except httpx.TransportError as error:
            return CheckResult.offline(error)

    @staticmethod
    def _status_check(response: httpx.Response, ok_text: str, fail_text: str) -> CheckResult:
        if response.status_code == HTTPStatus.OK:
            return CheckResult(ok=True, detail=ok_text)
        return CheckResult(ok=False, detail=f"{fail_text} (HTTP {response.status_code})")
