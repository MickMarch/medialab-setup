from http import HTTPStatus

import httpx
import pytest

from medialab_setup.checks import CredentialChecker
from medialab_setup.guides import Check


def _respond(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", "https://example.test"))


@pytest.mark.parametrize("check", list(Check))
def test_ok_status_is_accepted(check: Check, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _respond(HTTPStatus.OK))
    result = CredentialChecker().run(check, "value")
    assert result.ok and not result.unverified


def test_unauthorized_is_rejected_with_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _respond(HTTPStatus.UNAUTHORIZED))
    result = CredentialChecker().run(Check.TMDB, "value")
    assert not result.ok
    assert str(HTTPStatus.UNAUTHORIZED.value) in result.detail


def test_transport_error_is_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> httpx.Response:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", boom)
    result = CredentialChecker().run(Check.JELLYFIN, "value")
    assert result.ok and result.unverified


def test_secret_never_in_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _respond(HTTPStatus.FORBIDDEN))
    result = CredentialChecker().run(Check.DISCORD, "top-secret")
    assert "top-secret" not in result.detail
