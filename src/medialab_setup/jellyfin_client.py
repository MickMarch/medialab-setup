"""Register the library roots in Jellyfin on the host, once, and remove the
retired Discover libraries. Faked at this class in tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PureWindowsPath

import httpx
from medialab_contracts import MEDIA_TYPE_SUBDIRS, MediaType

from medialab_setup.checks import DEFAULT_JELLYFIN_URL, JELLYFIN_TOKEN_HEADER

VIRTUAL_FOLDERS_PATH = "/Library/VirtualFolders"
REQUEST_TIMEOUT_SECONDS = 30.0
COLLECTION_TYPES: dict[MediaType, str] = {MediaType.MOVIE: "movies", MediaType.SHOW: "tvshows"}
REFRESH_LIBRARY_OFF = "false"

# Retired Discover libraries (MickMarch/medialab#168): kept only to tear them down.
LEGACY_DISCOVER_LIBRARY_NAMES: tuple[str, ...] = ("Discover Movies", "Discover Shows")
LEGACY_DISCOVER_HOST_DIR_KEY = "DISCOVER_HOST_DIR"
LEGACY_DISCOVER_HOST_DIR_DEFAULT = "F:/MedialabDiscover"


@dataclass(frozen=True)
class Library:
    name: str
    collection_type: str | None
    paths: tuple[str, ...]


class JellyfinClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_JELLYFIN_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {JELLYFIN_TOKEN_HEADER: api_key}

    def list_libraries(self) -> list[Library]:
        response = httpx.get(
            f"{self.base_url}{VIRTUAL_FOLDERS_PATH}",
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return [
            Library(
                name=str(item.get("Name", "")),
                collection_type=item.get("CollectionType"),
                paths=tuple(str(path) for path in item.get("Locations", [])),
            )
            for item in response.json()
        ]

    def create_library(self, name: str, collection_type: str, path: str) -> None:
        response = httpx.post(
            f"{self.base_url}{VIRTUAL_FOLDERS_PATH}",
            headers=self.headers,
            params={
                "name": name,
                "collectionType": collection_type,
                "refreshLibrary": REFRESH_LIBRARY_OFF,
            },
            json={"LibraryOptions": {"PathInfos": [{"Path": path}]}},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def delete_library(self, name: str) -> None:
        response = httpx.delete(
            f"{self.base_url}{VIRTUAL_FOLDERS_PATH}",
            headers=self.headers,
            params={"name": name, "refreshLibrary": REFRESH_LIBRARY_OFF},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()


@dataclass
class DiscoverTeardown:
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def host_path(media_host_dir: str, subdir: str) -> str:
    """The path as Jellyfin on the Windows host sees it."""
    return str(PureWindowsPath(media_host_dir) / subdir)


def _same_path(left: str, right: str) -> bool:
    return PureWindowsPath(left).as_posix().lower() == PureWindowsPath(right).as_posix().lower()


def ensure_library_roots(client: JellyfinClient, media_host_dir: str) -> list[str]:
    """Create a library per media type whose path is not yet registered. Returns created names."""
    existing = client.list_libraries()
    created: list[str] = []
    for media_type, subdir in MEDIA_TYPE_SUBDIRS.items():
        path = host_path(media_host_dir, subdir)
        if any(_same_path(known, path) for library in existing for known in library.paths):
            continue
        client.create_library(subdir, COLLECTION_TYPES[media_type], path)
        created.append(subdir)
    return created


def _is_under(path: str, root: str) -> bool:
    folded = PureWindowsPath(path.lower())
    return folded.is_relative_to(PureWindowsPath(root.lower()))


def remove_discover_libraries(client: JellyfinClient, discover_host_dir: str) -> DiscoverTeardown:
    """Delete each retired Discover library whose every path is under the old Discover folder.

    A library with a Discover name and any other path is left alone and reported as skipped.
    """
    result = DiscoverTeardown()
    for library in client.list_libraries():
        if library.name not in LEGACY_DISCOVER_LIBRARY_NAMES:
            continue
        if library.paths and all(_is_under(path, discover_host_dir) for path in library.paths):
            client.delete_library(library.name)
            result.removed.append(library.name)
        else:
            result.skipped.append(library.name)
    return result


def legacy_discover_host_dir(root_env: Mapping[str, str]) -> str:
    """The old Discover folder from the root `.env`, or its old default."""
    return root_env.get(LEGACY_DISCOVER_HOST_DIR_KEY) or LEGACY_DISCOVER_HOST_DIR_DEFAULT


def report_discover_teardown(
    client: JellyfinClient, discover_host_dir: str, emit: Callable[[str], None]
) -> None:
    """Run the teardown; a Jellyfin error is a warning, never a failed run."""
    try:
        result = remove_discover_libraries(client, discover_host_dir)
    except httpx.HTTPError as error:
        emit(f"[yellow]warning:[/yellow] Discover libraries not removed: {error}")
        return
    if result.removed:
        emit(f"Removed retired Jellyfin libraries: {', '.join(result.removed)}")
    for name in result.skipped:
        emit(
            f"[yellow]warning:[/yellow] kept library {name!r}: it has paths outside "
            f"{discover_host_dir}"
        )
