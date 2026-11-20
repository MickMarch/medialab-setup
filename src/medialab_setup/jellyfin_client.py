"""Register the library roots in Jellyfin on the host, once, and remove the
retired Discover libraries. Faked at this class in tests."""

from __future__ import annotations

import ntpath
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PureWindowsPath

import httpx
from medialab_contracts import MEDIA_TYPE_SUBDIRS, MediaType

from medialab_setup.checks import DEFAULT_JELLYFIN_URL, jellyfin_auth_headers

VIRTUAL_FOLDERS_PATH = "/Library/VirtualFolders"
REQUEST_TIMEOUT_SECONDS = 30.0
COLLECTION_TYPES: dict[MediaType, str] = {MediaType.MOVIE: "movies", MediaType.SHOW: "tvshows"}
REFRESH_LIBRARY_OFF = "false"

# Retired Discover libraries (MickMarch/medialab#168): kept only to tear them down.
LEGACY_DISCOVER_LIBRARY_NAMES: tuple[str, ...] = ("Discover Movies", "Discover Shows")
LEGACY_DISCOVER_HOST_DIR_KEY = "DISCOVER_HOST_DIR"
LEGACY_DISCOVER_HOST_DIR_DEFAULT = "F:/MedialabDiscover"
# A drive or root alone ("F:", "F:/", "/") is never a safe teardown root.
MIN_DISCOVER_ROOT_PARTS = 2


class JellyfinResponseError(RuntimeError):
    """Jellyfin answered with a body that is not the expected library list."""


class UnsafeDiscoverRootError(ValueError):
    """The old Discover folder is a drive or root alone."""


@dataclass(frozen=True)
class Library:
    name: str
    collection_type: str | None
    paths: tuple[str, ...]


class JellyfinClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_JELLYFIN_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = jellyfin_auth_headers(api_key)

    def list_libraries(self) -> list[Library]:
        response = httpx.get(
            f"{self.base_url}{VIRTUAL_FOLDERS_PATH}",
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as error:
            raise JellyfinResponseError(f"library list is not JSON: {error}") from error
        return _parse_libraries(body)

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


def _parse_libraries(body: object) -> list[Library]:
    if not isinstance(body, list):
        raise JellyfinResponseError("library list is not a JSON array")
    libraries: list[Library] = []
    for item in body:
        if not isinstance(item, dict):
            raise JellyfinResponseError("library entry is not a JSON object")
        locations = item.get("Locations", [])
        if not isinstance(locations, list):
            raise JellyfinResponseError("library Locations is not a JSON array")
        collection_type = item.get("CollectionType")
        libraries.append(
            Library(
                name=str(item.get("Name", "")),
                collection_type=None if collection_type is None else str(collection_type),
                paths=tuple(str(path) for path in locations),
            )
        )
    return libraries


@dataclass
class DiscoverTeardown:
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


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


def _normalized(path: str) -> PureWindowsPath:
    return PureWindowsPath(ntpath.normpath(path).lower())


def _is_under(path: str, root: str) -> bool:
    return _normalized(path).is_relative_to(_normalized(root))


def is_safe_discover_root(discover_host_dir: str) -> bool:
    """False for an empty path, a drive alone or a root alone."""
    if not discover_host_dir.strip():
        return False
    return len(_normalized(discover_host_dir).parts) >= MIN_DISCOVER_ROOT_PARTS


def remove_discover_libraries(client: JellyfinClient, discover_host_dir: str) -> DiscoverTeardown:
    """Delete each retired Discover library whose every path is under the old Discover folder.

    A library with a Discover name and any other path is left alone and reported as skipped;
    a delete Jellyfin refuses is reported as failed. Listing errors propagate.
    """
    if not is_safe_discover_root(discover_host_dir):
        raise UnsafeDiscoverRootError(f"refusing Discover folder {discover_host_dir!r}")
    result = DiscoverTeardown()
    for library in client.list_libraries():
        if library.name not in LEGACY_DISCOVER_LIBRARY_NAMES:
            continue
        if not library.paths or not all(
            _is_under(path, discover_host_dir) for path in library.paths
        ):
            result.skipped.append(library.name)
            continue
        try:
            client.delete_library(library.name)
        except httpx.HTTPError:
            result.failed.append(library.name)
        else:
            result.removed.append(library.name)
    return result


def legacy_discover_host_dir(root_env: Mapping[str, str]) -> str:
    """The old Discover folder from the root `.env`, or its old default."""
    return root_env.get(LEGACY_DISCOVER_HOST_DIR_KEY) or LEGACY_DISCOVER_HOST_DIR_DEFAULT


def _left_behind_warning(names: Sequence[str], reason: str) -> str:
    return (
        f"[yellow]warning:[/yellow] retired Jellyfin libraries may be left behind "
        f"({', '.join(names)}): {reason}. Delete them in the Jellyfin dashboard under "
        f"Libraries, or rerun update."
    )


def report_discover_teardown(
    client: JellyfinClient, discover_host_dir: str, emit: Callable[[str], None]
) -> None:
    """Run the teardown; any failure is a warning naming what is left, never a failed run."""
    try:
        result = remove_discover_libraries(client, discover_host_dir)
    except UnsafeDiscoverRootError as error:
        emit(f"[yellow]warning:[/yellow] Discover teardown skipped: {error}")
        return
    except (httpx.HTTPError, JellyfinResponseError) as error:
        emit(_left_behind_warning(LEGACY_DISCOVER_LIBRARY_NAMES, str(error)))
        return
    if result.removed:
        emit(f"Removed retired Jellyfin libraries: {', '.join(result.removed)}")
    if result.failed:
        emit(_left_behind_warning(result.failed, "Jellyfin refused the delete"))
    for name in result.skipped:
        emit(
            f"[yellow]warning:[/yellow] kept library {name!r}: it has paths outside "
            f"{discover_host_dir}"
        )
