"""The container image serves the built frontend from the same process as the API (#32).

Off by default: in development Vite serves the frontend and proxies ``/api``. With
``STATIC_DIR`` set, the app serves that directory, and client-side routes fall back to
``index.html`` so a reload of ``/book/intro-call`` works.
"""

from pathlib import Path

import pytest

from tests.conftest import ClientFactory

INDEX = "<!doctype html><title>Call Calendar</title><div id=root></div>"
APP_JS = "console.log('app');"


@pytest.fixture
def frontend(tmp_path: Path) -> Path:
    """A tiny built frontend, with a secret file next to it that must never be served."""
    root = tmp_path / "site" / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "app.js").write_text(APP_JS)
    (tmp_path / "site" / "secret.txt").write_text("do not serve")
    return root


def test_without_a_static_directory_the_app_serves_only_the_api(make_client: ClientFactory) -> None:
    client = make_client()

    assert client.get("/").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


def test_the_index_page_is_served_at_the_root(make_client: ClientFactory, frontend: Path) -> None:
    client = make_client(static_dir=frontend)

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX


def test_built_files_are_served_with_their_own_type(
    make_client: ClientFactory, frontend: Path
) -> None:
    client = make_client(static_dir=frontend)

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == APP_JS
    assert "javascript" in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/book", "/book/intro-call", "/admin/bookings", "/no/such/page"])
def test_client_side_routes_fall_back_to_the_index_page(
    make_client: ClientFactory, frontend: Path, path: str
) -> None:
    client = make_client(static_dir=frontend)

    response = client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX


def test_a_missing_built_file_is_a_404_not_the_index_page(
    make_client: ClientFactory, frontend: Path
) -> None:
    client = make_client(static_dir=frontend)

    assert client.get("/assets/missing.js").status_code == 404


def test_api_and_health_keep_answering_in_json(make_client: ClientFactory, frontend: Path) -> None:
    client = make_client(static_dir=frontend)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/calendar").json()["owner"]["name"]

    unknown = client.get("/api/does-not-exist")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")
    assert INDEX not in unknown.text


@pytest.mark.parametrize(
    "path",
    ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/..%2fsecret.txt"],
)
def test_files_outside_the_static_directory_are_never_served(
    make_client: ClientFactory, frontend: Path, path: str
) -> None:
    client = make_client(static_dir=frontend)

    response = client.get(path)

    assert "do not serve" not in response.text


def test_a_static_directory_that_does_not_exist_stops_the_start(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="STATIC_DIR"):
        make_client(static_dir=tmp_path / "nope")
