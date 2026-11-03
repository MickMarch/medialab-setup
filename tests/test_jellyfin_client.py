from medialab_setup.jellyfin_client import (
    JellyfinClient,
    Library,
    ensure_discover_libraries,
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


def test_creates_both_discover_libraries_on_a_fresh_server() -> None:
    client = FakeJellyfin([])
    created = ensure_discover_libraries(client, "F:/MedialabDiscover")
    assert created == ["Discover Movies", "Discover Shows"]
    assert client.created == [
        ("Discover Movies", "movies", r"F:\MedialabDiscover\Movies"),
        ("Discover Shows", "tvshows", r"F:\MedialabDiscover\Shows"),
    ]


def test_an_existing_discover_library_is_kept_by_name() -> None:
    client = FakeJellyfin([Library("Discover Movies", "movies", (r"G:\Elsewhere\Movies",))])
    created = ensure_discover_libraries(client, "F:/MedialabDiscover")
    assert created == ["Discover Shows"]
    assert [name for name, _, _ in client.created] == ["Discover Shows"]


def test_a_discover_path_already_registered_is_not_added_again() -> None:
    client = FakeJellyfin([Library("Picks", "tvshows", ("f:/medialabdiscover/shows",))])
    assert ensure_discover_libraries(client, "F:/MedialabDiscover") == ["Discover Movies"]
