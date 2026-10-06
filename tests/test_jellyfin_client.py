from medialab_setup.jellyfin_client import (
    JellyfinClient,
    Library,
    ensure_library_roots,
    host_path,
)


class FakeJellyfin(JellyfinClient):
    def __init__(self, libraries: list[Library]) -> None:
        super().__init__(api_key="k")
        self.libraries = libraries
        self.created: list[tuple[str, str, str]] = []

    def list_libraries(self) -> list[Library]:
        return self.libraries

    def create_library(self, name: str, collection_type: str, path: str) -> None:
        self.created.append((name, collection_type, path))


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
