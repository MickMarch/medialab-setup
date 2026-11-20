from unittest.mock import MagicMock, patch

import httpx
import pytest

from medialab_setup.jellyfin_client import (
    LEGACY_DISCOVER_HOST_DIR_DEFAULT,
    LEGACY_DISCOVER_HOST_DIR_KEY,
    JellyfinClient,
    JellyfinResponseError,
    Library,
    ensure_library_roots,
    host_path,
    legacy_discover_host_dir,
    remove_discover_libraries,
    report_discover_teardown,
)

OLD_DISCOVER_DIR = "F:/MedialabDiscover"


class FakeJellyfin(JellyfinClient):
    def __init__(self, libraries: list[Library]) -> None:
        super().__init__(api_key="k")
        self.libraries = libraries
        self.created: list[tuple[str, str, str]] = []
        self.deleted: list[str] = []

    def list_libraries(self) -> list[Library]:
        return self.libraries

    def create_library(self, name: str, collection_type: str, path: str) -> None:
        self.created.append((name, collection_type, path))

    def delete_library(self, name: str) -> None:
        self.deleted.append(name)
        self.libraries = [library for library in self.libraries if library.name != name]


def test_host_path_uses_windows_separators() -> None:
    assert host_path("F:/Media", "Movies") == r"F:\Media\Movies"


def test_creates_both_libraries_on_a_fresh_server() -> None:
    client = FakeJellyfin([])
    created = ensure_library_roots(client, "F:/Media")
    assert created == ["Movies", "Shows"]
    assert client.created == [
        ("Movies", "movies", r"F:\Media\Movies"),
        ("Shows", "tvshows", r"F:\Media\Shows"),
    ]


def test_skips_paths_already_registered_regardless_of_case_or_slashes() -> None:
    client = FakeJellyfin(
        [
            Library("Films", "movies", (r"f:\media\MOVIES",)),
            Library("TV", "tvshows", ("F:/Media/Shows",)),
        ]
    )
    assert ensure_library_roots(client, "F:/Media") == []
    assert client.created == []


def test_staging_folder_is_never_registered() -> None:
    client = FakeJellyfin([])
    ensure_library_roots(client, "F:/Media")
    assert all("_incoming" not in path for _, _, path in client.created)


def _discover_libraries() -> list[Library]:
    return [
        Library("Movies", "movies", (r"F:\Media\Movies",)),
        Library("Discover Movies", "movies", (r"F:\MedialabDiscover\Movies",)),
        Library("Discover Shows", "tvshows", ("f:/medialabdiscover/shows",)),
    ]


def test_removes_both_discover_libraries_under_the_old_folder() -> None:
    client = FakeJellyfin(_discover_libraries())
    result = remove_discover_libraries(client, OLD_DISCOVER_DIR)
    assert client.deleted == ["Discover Movies", "Discover Shows"]
    assert result.removed == ["Discover Movies", "Discover Shows"]
    assert result.skipped == []
    assert [library.name for library in client.libraries] == ["Movies"]


def test_a_discover_name_with_a_foreign_path_is_skipped() -> None:
    client = FakeJellyfin(
        [
            Library("Discover Movies", "movies", (r"F:\MedialabDiscover\Movies", r"G:\Films")),
            Library("Discover Shows", "tvshows", (r"G:\Elsewhere\Shows",)),
        ]
    )
    result = remove_discover_libraries(client, OLD_DISCOVER_DIR)
    assert client.deleted == []
    assert result.removed == []
    assert result.skipped == ["Discover Movies", "Discover Shows"]


def test_a_library_with_another_name_under_the_old_folder_is_kept() -> None:
    client = FakeJellyfin([Library("Picks", "movies", (r"F:\MedialabDiscover\Movies",))])
    assert remove_discover_libraries(client, OLD_DISCOVER_DIR).removed == []
    assert client.deleted == []


def test_nothing_to_remove_makes_no_delete_call() -> None:
    client = FakeJellyfin([Library("Movies", "movies", (r"F:\Media\Movies",))])
    result = remove_discover_libraries(client, OLD_DISCOVER_DIR)
    assert client.deleted == []
    assert result.removed == [] and result.skipped == []


def test_running_twice_is_safe() -> None:
    client = FakeJellyfin(_discover_libraries())
    remove_discover_libraries(client, OLD_DISCOVER_DIR)
    second = remove_discover_libraries(client, OLD_DISCOVER_DIR)
    assert second.removed == []
    assert client.deleted == ["Discover Movies", "Discover Shows"]


class UnreachableJellyfin(FakeJellyfin):
    def list_libraries(self) -> list[Library]:
        raise httpx.ConnectError("refused")


def test_an_unreachable_jellyfin_is_a_warning_not_a_failure() -> None:
    lines: list[str] = []
    report_discover_teardown(UnreachableJellyfin([]), OLD_DISCOVER_DIR, lines.append)
    assert len(lines) == 1
    assert "Discover Movies" in lines[0] and "Discover Shows" in lines[0]
    assert "dashboard" in lines[0]


def test_old_folder_comes_from_the_root_env_or_the_old_default() -> None:
    assert legacy_discover_host_dir({LEGACY_DISCOVER_HOST_DIR_KEY: "G:/Old"}) == "G:/Old"
    assert legacy_discover_host_dir({}) == LEGACY_DISCOVER_HOST_DIR_DEFAULT


class BadShapeJellyfin(FakeJellyfin):
    def list_libraries(self) -> list[Library]:
        raise JellyfinResponseError("not a list")


def test_an_unexpected_jellyfin_body_is_a_warning_not_a_failure() -> None:
    lines: list[str] = []
    report_discover_teardown(BadShapeJellyfin([]), OLD_DISCOVER_DIR, lines.append)
    assert len(lines) == 1 and "dashboard" in lines[0]


class FailingDeleteJellyfin(FakeJellyfin):
    def delete_library(self, name: str) -> None:
        if name == "Discover Shows":
            raise httpx.ConnectError("refused")
        super().delete_library(name)


def test_a_failed_delete_names_only_the_library_left_behind() -> None:
    lines: list[str] = []
    client = FailingDeleteJellyfin(_discover_libraries())
    report_discover_teardown(client, OLD_DISCOVER_DIR, lines.append)
    assert client.deleted == ["Discover Movies"]
    warning = next(line for line in lines if "dashboard" in line)
    assert "Discover Shows" in warning and "Discover Movies" not in warning


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(ValueError("not json"), id="non-json"),
        pytest.param({"Name": "Movies"}, id="object-not-list"),
        pytest.param(["Movies"], id="list-of-strings"),
        pytest.param([{"Name": "Movies", "Locations": "F:/Media"}], id="locations-not-list"),
    ],
)
def test_list_libraries_raises_a_response_error_on_a_bad_body(body: object) -> None:
    response = MagicMock()
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    with (
        patch("medialab_setup.jellyfin_client.httpx.get", return_value=response),
        pytest.raises(JellyfinResponseError),
    ):
        JellyfinClient(api_key="k").list_libraries()


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(r"F:\MedialabDiscoverX\Movies", id="prefix-collision"),
        pytest.param(r"F:\MedialabDiscover\..\Movies", id="dot-dot-segment"),
        pytest.param(r"F:\Media\Movies", id="unrelated"),
    ],
)
def test_a_path_outside_the_old_folder_is_kept(path: str) -> None:
    client = FakeJellyfin([Library("Discover Movies", "movies", (path,))])
    result = remove_discover_libraries(client, OLD_DISCOVER_DIR)
    assert client.deleted == []
    assert result.skipped == ["Discover Movies"]


@pytest.mark.parametrize("root", ["F:", "F:/", "/", ""])
def test_a_drive_or_root_only_discover_folder_skips_the_teardown(root: str) -> None:
    lines: list[str] = []
    client = FakeJellyfin(_discover_libraries())
    report_discover_teardown(client, root, lines.append)
    assert client.deleted == []
    assert len(lines) == 1 and "warning" in lines[0]
