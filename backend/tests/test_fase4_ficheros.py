"""Fase 4: ficheros de distribución, descarga por rol y enlaces firmados (decisión 40)."""

import hashlib
import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditAction, AuditEvent, DistributionFile, Role, User
from app.security import create_download_token
from app.storage import DiskStorage, storage_key
from tests.conftest import BASE_URI
from tests.fase4_data import V1, editor_headers, publish, series, upload

CSV = b"a,b\r\n1,2\r\n"
PATH = "/dataset/prueba/1.0.0/{dist}/fichero"


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    headers = editor_headers(make_user, login)
    return headers


@pytest.fixture
def published(client: TestClient, editor) -> dict[str, str]:
    assert publish(client, editor, series(V1)).status_code == 201
    return editor


@pytest.fixture
def member(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("socia", Role.MIEMBRO)
    return login("socia")


def _dist(client: TestClient, name: str) -> dict:
    detail = client.get("/datasets/prueba").json()
    return next(d for d in detail["version"]["distributions"] if d["uri"].endswith(f"/{name}"))


# --- Subida ---------------------------------------------------------------------------


def test_upload_and_read_back(
    client: TestClient, published, file_storage: DiskStorage, db: Session
) -> None:
    response = upload(client, published, "abierta", CSV)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["storage_key"] == "prueba/1.0.0/abierta"
    assert body["byte_size"] == len(CSV)
    assert body["sha256"] == hashlib.sha256(CSV).hexdigest()
    assert body["media_type"] == "text/csv"  # del RDF, no del cliente
    assert (file_storage.root / "prueba" / "1.0.0" / "abierta").read_bytes() == CSV
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_UPLOADED.value)
    ).one()
    assert event.details["storage_key"] == "prueba/1.0.0/abierta"


def test_upload_same_content_is_idempotent(client: TestClient, published) -> None:
    upload(client, published, "abierta", CSV)
    assert upload(client, published, "abierta", CSV).status_code == 200


def test_upload_other_content_is_409(client: TestClient, published) -> None:
    upload(client, published, "abierta", CSV)
    response = upload(client, published, "abierta", b"otro")
    assert response.status_code == 409
    assert response.json()["detail"].startswith("file_exists")


def test_non_public_never_gets_a_file(
    client: TestClient, published, file_storage: DiskStorage
) -> None:
    response = upload(client, published, "defensa", CSV)
    assert response.status_code == 409
    assert response.json()["detail"].startswith("non_public")
    assert not (file_storage.root / "prueba" / "1.0.0" / "defensa").exists()


def test_upload_unknown_distribution_is_404(client: TestClient, published) -> None:
    assert upload(client, published, "no-existe", CSV).status_code == 404


def test_upload_too_large_is_413(client: TestClient, published, settings: Settings) -> None:
    settings.max_upload_mb = 1
    response = upload(client, published, "abierta", b"x" * (1024 * 1024 + 10))
    assert response.status_code == 413


def test_upload_requires_editor(client: TestClient, published, member) -> None:
    assert upload(client, {}, "abierta", CSV).status_code == 401
    assert upload(client, member, "abierta", CSV).status_code == 403


def test_upload_requires_multipart(client: TestClient, published) -> None:
    response = client.put(
        "/datasets/prueba/versions/1.0.0/distributions/abierta/file",
        content=CSV,
        headers=published | {"Content-Type": "text/csv"},
    )
    assert response.status_code == 415


@pytest.mark.parametrize("dist", ["..", "..%2F..%2Fetc", "Mayus", "a_b", "%2E%2E"])
def test_path_traversal_in_dist_is_rejected(client: TestClient, published, dist: str) -> None:
    response = client.put(
        f"/datasets/prueba/versions/1.0.0/distributions/{dist}/file",
        files={"file": ("x", b"x")},
        headers=published,
    )
    assert response.status_code in (404, 422)
    assert client.get(f"/dataset/prueba/1.0.0/{dist}/fichero").status_code in (404, 422)


def test_storage_key_rejects_traversal(tmp_path: Path) -> None:
    for bad in (("..", "1.0.0", "x"), ("a", "1.0.0", ".."), ("a", "../1", "x")):
        with pytest.raises(ValueError):
            storage_key(*bad)
    with pytest.raises(ValueError):
        DiskStorage(tmp_path).save("../../fuera/1.0.0/x", io.BytesIO(b"x"))


def test_disk_storage_is_atomic(tmp_path: Path) -> None:
    storage = DiskStorage(tmp_path)

    class Broken(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise OSError("se corta la subida")

    with pytest.raises(Exception, match="almacenamiento"):
        storage.save("a/1.0.0/x", Broken())
    assert not storage.exists("a/1.0.0/x")
    assert list((tmp_path / "a" / "1.0.0").iterdir()) == []  # sin temporales


# --- Estado en la ficha -----------------------------------------------------------------


def test_download_modes_in_detail(client: TestClient, published) -> None:
    upload(client, published, "abierta", CSV)
    upload(client, published, "restringida", CSV)
    abierta = _dist(client, "abierta")
    assert abierta["download"] == "open"
    assert abierta["download_url"] == f"{BASE_URI}dataset/prueba/1.0.0/abierta/fichero"
    assert abierta["byte_size"] == len(CSV)
    assert abierta["sha256"] == hashlib.sha256(CSV).hexdigest()
    assert _dist(client, "restringida")["download"] == "authenticated"
    defensa = _dist(client, "defensa")
    assert defensa["download"] == "metadata_only"
    assert defensa["download_url"] is None
    npz = _dist(client, "npz")
    assert npz["download"] == "unavailable"
    assert npz["download_url"] is None and npz["byte_size"] is None


# --- Descarga -------------------------------------------------------------------------


def test_open_download_for_anyone(client: TestClient, published, db: Session) -> None:
    upload(client, published, "abierta", CSV)
    response = client.get(PATH.format(dist="abierta"))
    assert response.status_code == 200
    assert response.content == CSV
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-length"] == str(len(CSV))
    assert response.headers["content-disposition"] == (
        'attachment; filename="prueba-1.0.0-abierta.csv"'
    )
    assert not db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_DOWNLOADED.value)
    ).all()


def test_restricted_download_needs_account(
    client: TestClient, published, member, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    assert client.get(PATH.format(dist="restringida")).status_code == 401
    response = client.get(PATH.format(dist="restringida"), headers=member)
    assert response.status_code == 200
    assert response.content == CSV
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_DOWNLOADED.value)
    ).one()
    assert event.actor_username == "socia"
    assert event.details["storage_key"] == "prueba/1.0.0/restringida"


def test_missing_file_and_non_public_are_404(client: TestClient, published, member) -> None:
    assert client.get(PATH.format(dist="npz"), headers=member).status_code == 404
    assert client.get(PATH.format(dist="defensa"), headers=member).status_code == 404


def test_file_without_media_type_is_octet_stream(client: TestClient, published, member) -> None:
    upload(client, published, "npz", b"PK\x03\x04")
    response = client.get(PATH.format(dist="npz"), headers=member)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].endswith('prueba-1.0.0-npz.npz"')


# --- Enlaces firmados -------------------------------------------------------------------


def _link(client: TestClient, headers: dict[str, str], dist: str = "restringida") -> str:
    response = client.post(
        f"/datasets/prueba/versions/1.0.0/distributions/{dist}/download-link", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["url"].startswith(f"/dataset/prueba/1.0.0/{dist}/fichero?token=")
    datetime.fromisoformat(body["expires_at"])
    return body["url"]


def test_signed_link_downloads_once(client: TestClient, published, member) -> None:
    upload(client, published, "restringida", CSV)
    url = _link(client, member)
    first = client.get(url)
    assert first.status_code == 200 and first.content == CSV
    assert client.get(url).status_code == 401  # un solo uso


def test_link_needs_account_and_file(client: TestClient, published, member) -> None:
    upload(client, published, "restringida", CSV)
    response = client.post(
        "/datasets/prueba/versions/1.0.0/distributions/restringida/download-link"
    )
    assert response.status_code == 401
    response = client.post(
        "/datasets/prueba/versions/1.0.0/distributions/npz/download-link", headers=member
    )
    assert response.status_code == 404


def test_link_for_another_file_is_rejected(client: TestClient, published, member) -> None:
    upload(client, published, "restringida", CSV)
    upload(client, published, "npz", b"npz")
    url = _link(client, member, "npz")
    token = url.split("token=", 1)[1]
    assert client.get(f"{PATH.format(dist='restringida')}?token={token}").status_code == 401


def test_expired_link_is_rejected(
    client: TestClient, published, settings: Settings, make_user, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    user = make_user("caducada", Role.MIEMBRO)
    token, _ = create_download_token(
        settings,
        user_id=user.id,
        storage_key="prueba/1.0.0/restringida",
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    assert client.get(f"{PATH.format(dist='restringida')}?token={token}").status_code == 401


def test_access_token_is_not_a_download_link(client: TestClient, published, member) -> None:
    upload(client, published, "restringida", CSV)
    access = member["Authorization"].split()[1]
    assert client.get(f"{PATH.format(dist='restringida')}?token={access}").status_code == 401


def test_download_link_is_not_an_access_token(
    client: TestClient, published, member, settings: Settings
) -> None:
    upload(client, published, "restringida", CSV)
    token = _link(client, member).split("token=", 1)[1]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["key"] == "prueba/1.0.0/restringida"
    assert claims["exp"] - claims["iat"] == settings.download_link_ttl_seconds


def test_link_of_deactivated_user_is_rejected(
    client: TestClient, published, member, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    url = _link(client, member)
    user = db.scalars(select(User).where(User.username == "socia")).one()
    user.is_active = False
    db.commit()
    assert client.get(url).status_code == 401


def test_file_record_has_no_triplestore_side_effects(
    client: TestClient, published, store, db: Session
) -> None:
    graph_before = len(store.get_graph(f"{BASE_URI}dataset/prueba"))
    upload(client, published, "abierta", CSV)
    assert len(store.get_graph(f"{BASE_URI}dataset/prueba")) == graph_before
    assert db.get(DistributionFile, "prueba/1.0.0/abierta") is not None
