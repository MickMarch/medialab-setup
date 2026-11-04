"""Register the library roots and the Discover libraries in Jellyfin on the
host, once. Faked at this class in tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath

import httpx
from medialab_contracts import DISCOVER_LIBRARY_NAMES, MEDIA_TYPE_SUBDIRS, MediaType

from medialab_setup.checks import DEFAULT_JELLYFIN_URL, JELLYFIN_TOKEN_HEADER

VIRTUAL_FOLDERS_PATH = "/Library/VirtualFolders"
REQUEST_TIMEOUT_SECONDS = 30.0
COLLECTION_TYPES: dict[MediaType, str] = {MediaType.MOVIE: "movies", MediaType.SHOW: "tvshows"}


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
            params={"name": name, "collectionType": collection_type, "refreshLibrary": "false"},
            json={"LibraryOptions": {"PathInfos": [{"Path": path}]}},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()


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


def ensure_discover_libraries(client: JellyfinClient, discover_host_dir: str) -> list[str]:
    """Create each Discover library missing by name and by path. Returns created names."""
    existing = client.list_libraries()
    names = {library.name for library in existing}
    created: list[str] = []
    for media_type, name in DISCOVER_LIBRARY_NAMES.items():
        path = host_path(discover_host_dir, MEDIA_TYPE_SUBDIRS[media_type])
        registered = any(_same_path(known, path) for library in existing for known in library.paths)
        if name in names or registered:
            continue
        client.create_library(name, COLLECTION_TYPES[media_type], path)
        created.append(name)
    return created
