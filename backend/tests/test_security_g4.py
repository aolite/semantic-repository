"""Seguridad y contrato de la fase 4 (G4): lo que no cubren ``test_fase4_*.py``.

Se organiza por superficie: inmutabilidad, descargas, subida, SPARQL público, login,
consultas guardadas, auditoría y 303. Los datos de la serie ``prueba`` están en
``fase4_data.py``. Todo es ficticio y local (doble en memoria de Fuseki).
"""

import hashlib
import io
import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sparql_public
from app.config import Settings, get_settings
from app.models import (
    AuditAction,
    AuditEvent,
    DistributionFile,
    FairEvaluation,
    Role,
    UsedDownloadToken,
    User,
)
from app.sparql_public import MemoryQueryRunner
from app.storage import DiskStorage
from app.triplestore import MemoryStore
from tests.conftest import BASE_URI, DEFAULT_PASSWORD, REPO_SEMANTIC_DIR
from tests.fase4_data import AR, IANA, V1, V2, publish, series, upload

CSV = b"a,b\r\n1,2\r\n"
FILE = "/dataset/prueba/1.0.0/{dist}/fichero"
LINK = "/datasets/prueba/versions/1.0.0/distributions/{dist}/download-link"
SQ_HEADERS = {"Content-Type": "application/sparql-query"}


# --- Fixtures -----------------------------------------------------------------------------


@pytest.fixture
def accounts(
    make_user: Callable[..., User], login: Callable[..., dict[str, str]]
) -> dict[str, dict[str, str]]:
    """Cabeceras de cada rol: miembro, editor y admin."""
    make_user("socia", Role.MIEMBRO)
    make_user("editora", Role.EDITOR)
    make_user("jefa", Role.ADMIN)
    return {"miembro": login("socia"), "editor": login("editora"), "admin": login("jefa")}


@pytest.fixture
def editor(accounts: dict[str, dict[str, str]]) -> dict[str, str]:
    return accounts["editor"]


@pytest.fixture
def member(accounts: dict[str, dict[str, str]]) -> dict[str, str]:
    return accounts["miembro"]


@pytest.fixture
def published(client: TestClient, editor: dict[str, str]) -> dict[str, str]:
    assert publish(client, editor, series(V1)).status_code == 201
    return editor


def _dist(slug_dist: str, **extra: str) -> str:
    """Turtle de una versión 3.0.0 con una distribución de ``dcat:mediaType`` CSV."""
    access = extra.get("access", "RESTRICTED")
    rights = f"dct:accessRights <{AR}{access}> ;" if access else ""
    dist_rights = (
        f"dct:accessRights <{AR}{extra['dist_access']}> ;" if "dist_access" in extra else ""
    )
    return f"""
<dataset/prueba/3.0.0> a dcat:Dataset ;
    dct:title "Prueba"@es ; dct:description "Versión 3"@es ;
    dcat:version "3.0.0" ; dcat:inSeries <dataset/prueba> ; {rights}
    dcat:distribution <dataset/prueba/3.0.0/{slug_dist}> .
<dataset/prueba/3.0.0/{slug_dist}> a dcat:Distribution ; {dist_rights}
    dcat:mediaType <{IANA}text/csv> ;
    dcat:accessURL <dataset/prueba/3.0.0/{slug_dist}> .
"""


def _audit_dump(db: Session) -> str:
    rows = db.scalars(select(AuditEvent)).all()
    return json.dumps(
        [
            {
                "action": r.action,
                "actor": r.actor_username,
                "target": r.target_username,
                "details": r.details,
            }
            for r in rows
        ],
        ensure_ascii=False,
    )


# ==========================================================================================
# 1. Inmutabilidad (decisión 28)
# ==========================================================================================


def test_adding_a_distribution_to_a_published_version_is_409(
    client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    publish(client, editor, series(V1))
    extra = f"""
<dataset/prueba/1.0.0> dcat:distribution <dataset/prueba/1.0.0/nueva> .
<dataset/prueba/1.0.0/nueva> a dcat:Distribution ;
    dcat:mediaType <{IANA}text/csv> ; dcat:accessURL <dataset/prueba/1.0.0/nueva> .
"""
    before = len(store.get_graph(f"{BASE_URI}dataset/prueba"))
    response = publish(client, editor, series(V1 + extra))
    assert response.status_code == 409
    assert response.json()["kind"] == "version_immutable"
    assert len(store.get_graph(f"{BASE_URI}dataset/prueba")) == before


def test_removing_a_distribution_from_a_published_version_is_409(
    client: TestClient, editor: dict[str, str]
) -> None:
    publish(client, editor, series(V1))
    without = V1.replace(", <dataset/prueba/1.0.0/npz>", "").replace(
        "<dataset/prueba/1.0.0/npz> a dcat:Distribution ;\n    dcat:accessURL "
        "<dataset/prueba/1.0.0/npz> .",
        "",
    )
    assert without != V1
    response = publish(client, editor, series(without))
    assert response.status_code == 409
    assert response.json()["kind"] == "version_immutable"


def test_relaxing_access_rights_by_republishing_is_409(
    client: TestClient, editor: dict[str, str], member: dict[str, str]
) -> None:
    """Cambiar RESTRICTED o NON_PUBLIC a PUBLIC republicando no puede abrir un fichero."""
    publish(client, editor, series(V1))
    open_up = V1.replace(f"<{AR}NON_PUBLIC>", f"<{AR}PUBLIC>")
    assert open_up != V1
    response = publish(client, editor, series(open_up))
    assert response.status_code == 409
    assert response.json()["kind"] == "version_immutable"
    assert (
        client.put(
            "/datasets/prueba/versions/1.0.0/distributions/defensa/file",
            files={"file": ("x.csv", CSV, "text/csv")},
            headers=editor,
        ).status_code
        == 409
    )


def test_changed_media_type_is_409(client: TestClient, editor: dict[str, str]) -> None:
    publish(client, editor, series(V1))
    other = V1.replace(f"<{IANA}text/csv>", f"<{IANA}application/json>")
    assert publish(client, editor, series(other)).status_code == 409


def test_conflict_is_atomic_new_version_is_not_published_or_evaluated(
    client: TestClient, editor: dict[str, str], db: Session, store: MemoryStore
) -> None:
    """Una petición con una versión alterada y otra nueva no escribe ni encola nada."""
    publish(client, editor, series(V1))
    evaluations = db.scalars(select(FairEvaluation.version_uri)).all()
    changed = V1.replace('"Versión 1"@es', '"Alterada"@es')
    response = publish(client, editor, series(changed, V2, last="2.0.0"))
    assert response.status_code == 409
    assert client.get("/datasets/prueba/versions/2.0.0").status_code == 404
    assert db.scalars(select(FairEvaluation.version_uri)).all() == evaluations
    assert not store.get_graph(f"{BASE_URI}dataset/prueba/2.0.0")


def test_conflict_is_not_audited_as_publication(
    client: TestClient, editor: dict[str, str], db: Session
) -> None:
    publish(client, editor, series(V1))
    published_events = db.scalars(select(AuditEvent)).all()
    publish(client, editor, series(V1.replace('"Versión 1"@es', '"X"@es')))
    assert db.scalars(select(AuditEvent)).all() == published_events


def test_republishing_is_idempotent_and_does_not_requeue(
    client: TestClient, editor: dict[str, str], db: Session
) -> None:
    publish(client, editor, series(V1))
    rows = db.scalars(select(FairEvaluation.id)).all()
    for _ in range(2):
        response = publish(client, editor, series(V1))
        assert response.status_code == 200 and response.json()["changed"] is False
    assert db.scalars(select(FairEvaluation.id)).all() == rows


def test_member_and_anonymous_cannot_publish(client: TestClient, member: dict[str, str]) -> None:
    assert publish(client, member, series(V1)).status_code == 403
    assert (
        client.post(
            "/datasets", content=series(V1).encode(), headers={"Content-Type": "text/turtle"}
        ).status_code
        == 401
    )


def _onto(body: str, version: str = "1.0.0") -> bytes:
    return f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
@prefix : <onto/prueba#> .
<onto/prueba> a owl:Ontology ; owl:versionIRI <onto/prueba/{version}> ;
    owl:versionInfo "{version}" ; adms:status <http://purl.org/adms/status/Completed> ;
    dct:title "Ontología de prueba"@es ; dct:description "Ontología de prueba"@es ;
    vann:preferredNamespacePrefix "prueba" ; vann:preferredNamespaceUri <onto/prueba#> .
{body}
""".encode()


@pytest.fixture
def no_reasoner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import owl_metrics, vocab_ingest

    def fake(prepared, settings):  # type: ignore[no-untyped-def]
        metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri).to_dict()
        return metrics, owl_metrics.Consistency(detail="sin razonador").to_dict()

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fake)


def test_ontology_republish_with_other_content_is_409_and_keeps_stored_version(
    client: TestClient, editor: dict[str, str], store: MemoryStore, no_reasoner: None
) -> None:
    headers = editor | {"Content-Type": "text/turtle"}
    assert client.post("/ontologies", content=_onto(":A a owl:Class ."), headers=headers)
    graph = f"{BASE_URI}onto/prueba/1.0.0"
    before = {str(t) for t in store.get_graph(graph)}
    assert before
    for body in (
        ":A a owl:Class . :B a owl:Class .",  # más
        ":A a owl:Class ; rdfs:label 'cambiada'@es .",  # distinto
        "",  # menos
    ):
        response = client.post("/ontologies", content=_onto(body), headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["kind"] == "version_immutable"
        assert {str(t) for t in store.get_graph(graph)} == before


def test_ontology_republish_same_content_is_idempotent_and_new_version_is_added(
    client: TestClient, editor: dict[str, str], store: MemoryStore, no_reasoner: None
) -> None:
    headers = editor | {"Content-Type": "text/turtle"}
    first = client.post("/ontologies", content=_onto(":A a owl:Class ."), headers=headers)
    second = client.post("/ontologies", content=_onto(":A a owl:Class ."), headers=headers)
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    newer = client.post(
        "/ontologies", content=_onto(":A a owl:Class . :B a owl:Class .", "1.1.0"), headers=headers
    )
    assert newer.status_code == 201, newer.text
    assert len(store.get_graph(f"{BASE_URI}onto/prueba/1.0.0")) > 0


def test_ontology_ingest_needs_editor(client: TestClient, member: dict[str, str]) -> None:
    headers = member | {"Content-Type": "text/turtle"}
    assert (
        client.post("/ontologies", content=_onto(":A a owl:Class ."), headers=headers).status_code
        == 403
    )
    assert (
        client.post(
            "/ontologies",
            content=_onto(":A a owl:Class ."),
            headers={"Content-Type": "text/turtle"},
        ).status_code
        == 401
    )


# ==========================================================================================
# 2. Descargas
# ==========================================================================================


@pytest.mark.parametrize("role", ["miembro", "editor", "admin"])
def test_restricted_download_is_open_to_every_account_role(
    client: TestClient, published, accounts, role: str, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    response = client.get(FILE.format(dist="restringida"), headers=accounts[role])
    assert response.status_code == 200 and response.content == CSV
    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_DOWNLOADED.value)
    ).one()
    assert event.details["storage_key"] == "prueba/1.0.0/restringida"


def test_anonymous_never_gets_restricted_file_by_any_route(
    client: TestClient, published, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    url = FILE.format(dist="restringida")
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer "}).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer basura"}).status_code == 401
    assert client.get(url, headers={"Authorization": "Basic YTpi"}).status_code == 401
    assert client.get(url + "?token=").status_code == 401
    assert client.get(url + "?token=basura").status_code == 401
    assert client.head(url).status_code in (401, 405)
    assert client.post(LINK.format(dist="restringida")).status_code == 401
    assert not db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_DOWNLOADED.value)
    ).all()


def test_open_download_ignores_token_and_does_not_consume_it(
    client: TestClient, published, member, db: Session
) -> None:
    upload(client, published, "abierta", CSV)
    response = client.get(FILE.format(dist="abierta") + "?token=basura")
    assert response.status_code == 200
    assert db.scalars(select(UsedDownloadToken)).all() == []


@pytest.mark.parametrize("role", ["anonimo", "miembro", "editor", "admin"])
def test_non_public_is_never_served_even_if_a_file_exists(
    client: TestClient,
    published,
    accounts,
    role: str,
    db: Session,
    file_storage: DiskStorage,
) -> None:
    """Defensa en profundidad: si por error hay un fichero NON_PUBLIC, tampoco se sirve."""
    key = "prueba/1.0.0/defensa"
    file_storage.save(key, io.BytesIO(CSV))
    db.add(
        DistributionFile(
            storage_key=key,
            distribution_uri=f"{BASE_URI}dataset/prueba/1.0.0/defensa",
            media_type="text/csv",
            byte_size=len(CSV),
            sha256=hashlib.sha256(CSV).hexdigest(),
        )
    )
    db.commit()
    headers = {} if role == "anonimo" else accounts[role]
    assert client.get(FILE.format(dist="defensa"), headers=headers).status_code == 404
    token = _signed(client, key)
    assert client.get(FILE.format(dist="defensa") + f"?token={token}").status_code == 404
    if role != "anonimo":
        assert client.post(LINK.format(dist="defensa"), headers=headers).status_code == 404
    detail = client.get("/datasets/prueba").json()["version"]["distributions"]
    defensa = next(d for d in detail if d["uri"].endswith("/defensa"))
    assert defensa["download"] == "metadata_only" and defensa["download_url"] is None


def _signed(_client: TestClient, key: str, **overrides: object) -> str:
    """Token de descarga bien firmado para ``key`` y un usuario inexistente; claims
    sobrescribibles."""
    cfg = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "aud": "itot-download",
        "sub": str(uuid.uuid4()),
        "key": key,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(seconds=60),
    }
    claims.update(overrides)
    return jwt.encode(claims, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


@pytest.mark.parametrize(
    ("access", "dist_access", "mode", "upload_status"),
    [
        ("NON_PUBLIC", None, "metadata_only", 409),  # hereda NON_PUBLIC
        ("PUBLIC", "NON_PUBLIC", "metadata_only", 409),  # la distribución manda
        ("RESTRICTED", "NON_PUBLIC", "metadata_only", 409),
        ("RESTRICTED", "PUBLIC", "open", 201),
        ("PUBLIC", "RESTRICTED", "authenticated", 201),
        ("PUBLIC", None, "open", 201),
    ],
)
def test_effective_access_rights(
    client: TestClient,
    editor,
    member,
    access: str,
    dist_access: str | None,
    mode: str,
    upload_status: int,
) -> None:
    """El accessRights efectivo es el de la distribución o, si no tiene, el de la versión."""
    publish(client, editor, series(V1))
    extra = {"access": access} | ({"dist_access": dist_access} if dist_access else {})
    response = publish(client, editor, series(V1, _dist("datos", **extra), last="3.0.0"))
    assert response.status_code == 200, response.text
    put = client.put(
        "/datasets/prueba/versions/3.0.0/distributions/datos/file",
        files={"file": ("x.csv", CSV, "text/csv")},
        headers=editor,
    )
    assert put.status_code == upload_status, put.text
    detail = client.get("/datasets/prueba").json()["version"]
    distribution = next(d for d in detail["distributions"] if d["uri"].endswith("/datos"))
    expected = mode if upload_status == 201 or mode == "metadata_only" else "unavailable"
    assert distribution["download"] == expected
    url = "/dataset/prueba/3.0.0/datos/fichero"
    anonymous = client.get(url).status_code
    assert anonymous == {"open": 200, "authenticated": 401, "metadata_only": 404}[mode]
    if mode == "metadata_only":
        assert client.get(url, headers=member).status_code == 404


def test_access_right_outside_european_table_is_unavailable_and_not_downloadable(
    client: TestClient, editor, member, db: Session, file_storage: DiskStorage
) -> None:
    bad = V1.replace(f"<{AR}NON_PUBLIC>", "<http://ejemplo.org/acceso-raro>")
    publish(client, editor, series(bad))
    key = "prueba/1.0.0/defensa"
    file_storage.save(key, io.BytesIO(CSV))
    db.add(
        DistributionFile(
            storage_key=key,
            distribution_uri=f"{BASE_URI}dataset/prueba/1.0.0/defensa",
            media_type="text/csv",
            byte_size=len(CSV),
            sha256=hashlib.sha256(CSV).hexdigest(),
        )
    )
    db.commit()
    assert client.get(FILE.format(dist="defensa"), headers=member).status_code == 404
    assert client.post(LINK.format(dist="defensa"), headers=member).status_code == 404


def test_restricted_response_headers(client: TestClient, published, member) -> None:
    upload(client, published, "restringida", CSV)
    response = client.get(FILE.format(dist="restringida"), headers=member)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]
    assert "private" in response.headers["cache-control"]
    assert "inline" not in response.headers["content-disposition"]


def _link(client: TestClient, headers: dict[str, str], dist: str = "restringida") -> str:
    response = client.post(LINK.format(dist=dist), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["url"]


def test_link_cannot_be_forged_with_another_secret_or_alg_none(
    client: TestClient, published, member
) -> None:
    upload(client, published, "restringida", CSV)
    key = "prueba/1.0.0/restringida"
    good = _link(client, member).split("token=", 1)[1]
    claims = jwt.decode(good, options={"verify_signature": False})
    forged = jwt.encode(claims, "otro-secreto-de-32-caracteres-xxxxxxxx", algorithm="HS256")
    assert client.get(FILE.format(dist="restringida") + f"?token={forged}").status_code == 401
    none_alg = jwt.encode(claims, None, algorithm="none")
    assert client.get(FILE.format(dist="restringida") + f"?token={none_alg}").status_code == 401
    head, payload, signature = good.split(".")
    tampered = ".".join([head, payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB"), signature])
    assert client.get(FILE.format(dist="restringida") + f"?token={tampered}").status_code == 401
    # Con un sub que no es un usuario (token firmado bien, pero de nadie).
    ghost = _signed(client, key)
    assert client.get(FILE.format(dist="restringida") + f"?token={ghost}").status_code == 401


@pytest.mark.parametrize("missing", ["aud", "jti", "key", "sub", "exp"])
def test_link_without_required_claim_is_rejected(
    client: TestClient, published, member, missing: str
) -> None:
    upload(client, published, "restringida", CSV)
    good = _link(client, member).split("token=", 1)[1]
    claims = jwt.decode(good, options={"verify_signature": False})
    claims.pop(missing)
    token = jwt.encode(claims, get_settings().jwt_secret, algorithm="HS256")
    assert client.get(FILE.format(dist="restringida") + f"?token={token}").status_code == 401


def test_link_for_other_version_or_slug_is_rejected(client: TestClient, published, member) -> None:
    upload(client, published, "restringida", CSV)
    publish(client, published, series(V1, _dist("datos"), last="3.0.0"))
    upload(client, published, "datos", CSV, version="3.0.0")
    token = _link(client, member).split("token=", 1)[1]
    other = "/dataset/prueba/3.0.0/datos/fichero"
    assert client.get(f"{other}?token={token}").status_code == 401
    other_slug = "/dataset/otro/1.0.0/restringida/fichero"
    assert client.get(f"{other_slug}?token={token}").status_code == 404


def test_link_is_single_use_even_when_replayed_with_other_headers(
    client: TestClient, published, member, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    url = _link(client, member)
    assert client.get(url).status_code == 200
    for _ in range(3):
        assert client.get(url, headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 401
    assert len(db.scalars(select(UsedDownloadToken)).all()) == 1
    downloads = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_DOWNLOADED.value)
    ).all()
    assert len(downloads) == 1


def test_expired_link_is_not_marked_as_used(
    client: TestClient, published, settings: Settings, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    key = "prueba/1.0.0/restringida"
    token = _signed(client, key, exp=datetime.now(UTC) - timedelta(seconds=5))
    assert client.get(FILE.format(dist="restringida") + f"?token={token}").status_code == 401
    assert db.scalars(select(UsedDownloadToken)).all() == []


def test_link_ttl_is_bounded_by_settings(client: TestClient, member, published) -> None:
    upload(client, published, "restringida", CSV)
    response = client.post(LINK.format(dist="restringida"), headers=member).json()
    token = response["url"].split("token=", 1)[1]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] <= 300


def test_link_dies_with_role_change_and_deactivation(
    client: TestClient, published, accounts, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    admin = accounts["admin"]
    user = db.scalars(select(User).where(User.username == "socia")).one()
    url = _link(client, accounts["miembro"])
    changed = client.patch(f"/users/{user.id}", json={"role": "editor"}, headers=admin)
    assert changed.status_code == 200, changed.text
    assert client.get(url).status_code == 401
    # Una baja posterior también invalida lo emitido antes.
    fresh_login = client.post(
        "/auth/token", data={"username": "socia", "password": DEFAULT_PASSWORD}
    )
    headers = {"Authorization": f"Bearer {fresh_login.json()['access_token']}"}
    url2 = _link(client, headers)
    client.patch(f"/users/{user.id}", json={"is_active": False}, headers=admin)
    client.patch(f"/users/{user.id}", json={"is_active": True}, headers=admin)
    assert client.get(url2).status_code == 401  # reactivar no revive el enlace


def test_revoked_session_token_cannot_download(
    client: TestClient, published, accounts, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    user = db.scalars(select(User).where(User.username == "socia")).one()
    client.patch(f"/users/{user.id}", json={"is_active": False}, headers=accounts["admin"])
    response = client.get(FILE.format(dist="restringida"), headers=accounts["miembro"])
    assert response.status_code == 401


# --- Path traversal en slug, version y dist ---------------------------------------------

HOSTILE = [
    "..",
    "%2e%2e",
    "..%2f..%2fetc%2fpasswd",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "..%5c..%5cwindows",
    "....//",
    "%00",
    "a%00b",
    "a%0d%0aSet-Cookie:x=1",
    "%2fetc%2fpasswd",
    "a b",
    "A_B",
    "x" * 300,
    "ñ",
]


@pytest.fixture
def secret_outside(file_storage: DiskStorage, tmp_path: Path) -> Path:
    """Un fichero fuera de la raíz de almacenamiento que nunca debe servirse."""
    outside = tmp_path / "fuera.txt"
    outside.write_text("CONTENIDO-FUERA-DE-LA-RAIZ", encoding="utf-8")
    return outside


@pytest.mark.parametrize("hostile", HOSTILE)
@pytest.mark.parametrize(
    "template",
    [
        "/dataset/{h}/1.0.0/restringida/fichero",
        "/dataset/prueba/{h}/restringida/fichero",
        "/dataset/prueba/1.0.0/{h}/fichero",
    ],
)
def test_download_path_traversal_is_never_served(
    client: TestClient, published, member, secret_outside, template: str, hostile: str
) -> None:
    upload(client, published, "restringida", CSV)
    response = client.get(template.format(h=hostile), headers=member)
    assert response.status_code in (404, 422), (template, hostile, response.status_code)
    assert "CONTENIDO-FUERA" not in response.text
    assert "root:" not in response.text


@pytest.mark.parametrize("hostile", HOSTILE)
@pytest.mark.parametrize(
    "template",
    [
        "/datasets/{h}/versions/1.0.0/distributions/restringida/download-link",
        "/datasets/prueba/versions/{h}/distributions/restringida/download-link",
        "/datasets/prueba/versions/1.0.0/distributions/{h}/download-link",
        "/datasets/prueba/versions/{h}/fair/report",
    ],
)
def test_link_and_report_path_traversal_is_rejected(
    client: TestClient, published, member, template: str, hostile: str
) -> None:
    method = client.get if template.endswith("report") else client.post
    response = method(template.format(h=hostile), headers=member)
    assert response.status_code in (404, 405, 422), (template, hostile, response.status_code)


@pytest.mark.parametrize("hostile", HOSTILE)
def test_upload_path_traversal_writes_nothing(
    client: TestClient, published, tmp_path: Path, file_storage: DiskStorage, hostile: str
) -> None:
    for template in (
        "/datasets/{h}/versions/1.0.0/distributions/abierta/file",
        "/datasets/prueba/versions/{h}/distributions/abierta/file",
        "/datasets/prueba/versions/1.0.0/distributions/{h}/file",
    ):
        response = client.put(
            template.format(h=hostile), files={"file": ("x", CSV, "text/csv")}, headers=published
        )
        assert response.status_code in (404, 405, 422), (template, hostile)
    created = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert created == []


def test_symlink_in_storage_is_not_followed(
    client: TestClient, published, member, db: Session, file_storage: DiskStorage, tmp_path: Path
) -> None:
    """Si alguien deja un enlace simbólico en la carpeta, no se sirve lo de fuera."""
    secret = tmp_path / "secreto.txt"
    secret.write_text("SECRETO-FUERA", encoding="utf-8")
    folder = file_storage.root / "prueba" / "1.0.0"
    folder.mkdir(parents=True)
    (folder / "restringida").symlink_to(secret)
    db.add(
        DistributionFile(
            storage_key="prueba/1.0.0/restringida",
            distribution_uri=f"{BASE_URI}dataset/prueba/1.0.0/restringida",
            media_type="text/csv",
            byte_size=13,
            sha256="0" * 64,
        )
    )
    db.commit()
    try:
        response = client.get(FILE.format(dist="restringida"), headers=member)
    except ValueError:  # la defensa de DiskStorage salta (hoy sin traducir a 404)
        return
    assert "SECRETO-FUERA" not in response.text


# ==========================================================================================
# 3. Subida
# ==========================================================================================


def _put(client: TestClient, dist: str, headers: dict[str, str] | None, data: bytes = CSV):
    return client.put(
        f"/datasets/prueba/versions/1.0.0/distributions/{dist}/file",
        files={"file": ("x.csv", data, "text/csv")},
        headers=headers or {},
    )


@pytest.mark.parametrize(
    ("role", "status"),
    [("anonimo", 401), ("miembro", 403), ("editor", 201), ("admin", 201)],
)
def test_upload_by_role(client: TestClient, published, accounts, role: str, status: int) -> None:
    headers = None if role == "anonimo" else accounts[role]
    assert _put(client, "abierta", headers).status_code == status


def test_upload_rejects_forged_and_revoked_tokens(
    client: TestClient, published, accounts, db: Session
) -> None:
    assert _put(client, "abierta", {"Authorization": "Bearer x.y.z"}).status_code == 401
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        },
        "otro-secreto-de-32-caracteres-xxxxxxxx",
        algorithm="HS256",
    )
    assert _put(client, "abierta", {"Authorization": f"Bearer {token}"}).status_code == 401


def test_upload_never_lands_for_non_public_nor_unknown(
    client: TestClient, published, tmp_path: Path, db: Session
) -> None:
    assert _put(client, "defensa", published).status_code == 409
    assert _put(client, "no-existe", published).status_code == 404
    assert db.scalars(select(DistributionFile)).all() == []
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_file_exists_keeps_original_content(client: TestClient, published, member) -> None:
    assert _put(client, "restringida", published, b"original").status_code == 201
    other = _put(client, "restringida", published, b"otro contenido")
    assert other.status_code == 409 and "file_exists" in other.json()["detail"]
    assert client.get(FILE.format(dist="restringida"), headers=member).content == b"original"


def test_upload_413_without_content_length_stores_nothing(
    client: TestClient, published, settings: Settings, db: Session, tmp_path: Path
) -> None:
    settings.max_upload_mb = 1

    def body() -> Iterator[bytes]:
        for _ in range(4):  # 4 MiB sin Content-Length (transferencia en trozos)
            yield b"x" * (1024 * 1024)

    boundary = "frontera"
    prefix = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode()

    def stream() -> Iterator[bytes]:
        yield prefix
        yield from body()
        yield f"\r\n--{boundary}--\r\n".encode()

    response = client.put(
        "/datasets/prueba/versions/1.0.0/distributions/abierta/file",
        content=stream(),
        headers=published | {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 413
    assert db.scalars(select(DistributionFile)).all() == []
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_upload_rejects_two_files_and_missing_file(client: TestClient, published) -> None:
    url = "/datasets/prueba/versions/1.0.0/distributions/abierta/file"
    two = client.put(
        url,
        files=[("file", ("a.csv", CSV, "text/csv")), ("file", ("b.csv", CSV, "text/csv"))],
        headers=published,
    )
    assert two.status_code == 400
    other_field = client.put(url, files={"otro": ("a.csv", CSV, "text/csv")}, headers=published)
    assert other_field.status_code == 400


def test_upload_takes_media_type_from_rdf_not_from_client(
    client: TestClient, published, member
) -> None:
    response = client.put(
        "/datasets/prueba/versions/1.0.0/distributions/restringida/file",
        files={"file": ("shell.html", b"<script>1</script>", "text/html")},
        headers=published,
    )
    assert response.status_code == 201
    assert response.json()["media_type"] == "text/csv"
    served = client.get(FILE.format(dist="restringida"), headers=member)
    assert served.headers["content-type"].startswith("text/csv")
    assert served.headers["content-disposition"].startswith("attachment;")


def test_upload_is_audited_without_content(client: TestClient, published, db: Session) -> None:
    _put(client, "abierta", published, b"CONTENIDO-SECRETO-DEL-FICHERO")
    dump = _audit_dump(db)
    assert AuditAction.DISTRIBUTION_UPLOADED.value in dump
    assert "CONTENIDO-SECRETO" not in dump


# ==========================================================================================
# 4. SPARQL público
# ==========================================================================================


def _sparql(client: TestClient, query: str, **kwargs):
    return client.post(
        "/sparql", content=query.encode("utf-8"), headers=SQ_HEADERS | kwargs.pop("headers", {})
    )


@pytest.mark.parametrize(
    "query",
    [
        "WITH <https://semantic.example.org/itot/catalogo> DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "INSERT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "insert data { <http://a> <http://b> <http://c> }",
        "COPY DEFAULT TO <http://ejemplo.org/g>",
        "MOVE DEFAULT TO <http://ejemplo.org/g>",
        "ADD DEFAULT TO <http://ejemplo.org/g>",
        "CREATE GRAPH <http://ejemplo.org/g>",
        "CLEAR ALL",
        "DROP SILENT GRAPH <http://ejemplo.org/g>",
        "# SELECT * {}\nDROP ALL",
        "PREFIX x: <http://x/> DROP ALL",
        "DROP ALL ; SELECT * { ?s ?p ?o }",
        "SELECT * { ?s ?p ?o } ; DROP ALL",
        "ASK {} ; INSERT DATA { <http://a> <http://b> <http://c> }",
    ],
)
def test_every_kind_of_update_is_400_and_never_reaches_the_store(
    client: TestClient, query_runner: MemoryQueryRunner, query: str
) -> None:
    for response in (
        client.get("/sparql", params={"query": query}),
        _sparql(client, query),
        client.post("/sparql", data={"query": query}),
    ):
        assert response.status_code == 400, response.text
    assert query_runner.queries == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * { FILTER EXISTS { SERVICE <http://x/> { ?s ?p ?o } } }",
        "SELECT * { ?s ?p ?o FILTER NOT EXISTS { SERVICE <http://x/> { ?s ?p ?o } } }",
        "SELECT * { ?s ?p ?o MINUS { SERVICE <http://x/> { ?s ?p ?o } } }",
        "SELECT * { { ?s ?p ?o } UNION { SERVICE <http://x/> { ?s ?p ?o } } }",
        "SELECT * { GRAPH ?g { SERVICE <http://x/> { ?s ?p ?o } } }",
        "SELECT * { ?s ?p ?o . SERVICE ?u { ?a ?b ?c } }",
        "select * { service <http://x/> { ?a ?b ?c } }",
        "CONSTRUCT { ?s ?p ?o } WHERE { SERVICE <http://x/> { ?s ?p ?o } }",
        "DESCRIBE ?s WHERE { SERVICE <http://x/> { ?s ?p ?o } }",
        "SELECT * { ?s ?p ?o BIND(EXISTS { SERVICE <http://x/> { ?a ?b ?c } } AS ?e) }",
        "SELECT * { { SELECT ?s { { SELECT ?s { SERVICE <http://x/> { ?s ?p ?o } } } } } }",
        "SELECT * { SERVICE <http://x/> { SERVICE <http://y/> { ?a ?b ?c } } }",
        "SELECT * { VALUES ?x { 1 } SERVICE <http://x/> { ?s ?p ?o } }",
        "SELECT * { \\u0053ERVICE <http://x/> { ?a ?b ?c } }",
    ],
)
def test_service_is_rejected_everywhere_in_the_query(
    client: TestClient, query_runner: MemoryQueryRunner, query: str
) -> None:
    response = _sparql(client, query)
    assert response.status_code == 400, (query, response.status_code, response.text)
    assert query_runner.queries == []


@pytest.mark.parametrize(
    "query",
    [
        "ASK FROM <http://ejemplo.org/g> { ?s ?p ?o }",
        "CONSTRUCT { ?s ?p ?o } FROM <http://ejemplo.org/g> WHERE { ?s ?p ?o }",
        "DESCRIBE <http://a> FROM NAMED <http://ejemplo.org/g>",
        "SELECT * FROM <file:///etc/passwd> { ?s ?p ?o }",
        "SELECT * FROM <http://127.0.0.1:3030/itot/data> { ?s ?p ?o }",
        "SELECT * FROM <https://semantic.example.org/itot.evil.test/x> { ?s ?p ?o }",
        "SELECT * FROM <https://semantic.example.org/otra-ruta> { ?s ?p ?o }",
        "BASE <http://ejemplo.org/> SELECT * FROM <g> { ?s ?p ?o }",
        "SELECT * FROM <relativo> { ?s ?p ?o }",
        f"SELECT * FROM <{BASE_URI}catalogo> FROM <http://ejemplo.org/g> {{ ?s ?p ?o }}",  # noqa: S608
        "SELECT * FROM <HTTPS://SEMANTIC.EXAMPLE.ORG/itot/catalogo> { ?s ?p ?o }",
    ],
)
def test_foreign_from_is_rejected_in_every_query_form(
    client: TestClient, query_runner: MemoryQueryRunner, query: str
) -> None:
    response = _sparql(client, query)
    assert response.status_code == 400, (query, response.status_code, response.text)
    assert query_runner.queries == []


def test_from_with_base_resolves_into_the_repository() -> None:
    query = f"BASE <{BASE_URI}> SELECT * FROM <catalogo> {{ ?s ?p ?o }}"  # noqa: S608
    assert sparql_public.validate(query, BASE_URI).kind == "SELECT"


@pytest.mark.parametrize(
    "build",
    [
        lambda: "SELECT * WHERE {" + "{" * 3000 + "?s ?p ?o" + "}" * 3000 + "}",
        lambda: "SELECT * WHERE { ?s ?p ?o FILTER(" + "(" * 4000 + "1" + ")" * 4000 + ") }",
        lambda: "SELECT * WHERE { " + "?s ?p ?o . " * 1800 + "}",
        lambda: "SELECT * WHERE { ?s " + "/".join(["<http://p>"] * 1500) + " ?o }",
        lambda: "ASK { " + "OPTIONAL { " * 1500 + "?s ?p ?o" + " }" * 1500 + " }",
    ],
)
def test_pathological_queries_within_20kb_never_crash(
    client: TestClient, query_runner: MemoryQueryRunner, build: Callable[[], str]
) -> None:
    query = build()
    assert len(query.encode()) <= 20 * 1024
    response = _sparql(client, query)
    assert response.status_code in (200, 400), response.status_code
    assert "Traceback" not in response.text and "RecursionError" not in response.text


def test_20kb_boundary(client: TestClient) -> None:
    head = "ASK { ?s ?p ?o } #"
    exact = head + "x" * (20 * 1024 - len(head))
    assert len(exact.encode()) == 20 * 1024
    assert _sparql(client, exact).status_code == 200
    assert _sparql(client, exact + "x").status_code == 413
    # Cuenta bytes, no caracteres: 'ñ' ocupa dos.
    multibyte = head + "ñ" * (10 * 1024)
    assert _sparql(client, multibyte).status_code == 413


def test_huge_declared_content_length_is_413_before_reading(client: TestClient) -> None:
    response = client.post(
        "/sparql",
        content=b"ASK {}",
        headers=SQ_HEADERS | {"Content-Length": str(50 * 1024 * 1024)},
    )
    assert response.status_code in (400, 413)


def test_chunked_oversized_body_is_413(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(64):
            yield b"#" + b"x" * 1023

    response = client.post("/sparql", content=chunks(), headers=SQ_HEADERS)
    assert response.status_code == 413


def test_oversized_form_is_413(client: TestClient) -> None:
    response = client.post("/sparql", data={"query": "ASK {} #" + "x" * 200_000})
    assert response.status_code == 413
    percent = client.post(
        "/sparql",
        content=b"query=" + b"%41" * 21_000,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert percent.status_code == 413


def test_invalid_utf8_and_duplicated_query_fields(client: TestClient) -> None:
    assert (
        client.post("/sparql", content=b"ASK {} #\xff\xfe", headers=SQ_HEADERS).status_code == 400
    )
    dup = client.post(
        "/sparql",
        content=b"query=ASK%20%7B%7D&query=DROP%20ALL",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert dup.status_code == 400
    flood = "&".join(f"f{i}=1" for i in range(500)) + "&query=ASK%20%7B%7D"
    response = client.post(
        "/sparql",
        content=flood.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code in (400, 413)


@pytest.mark.parametrize("method", ["put", "delete", "patch"])
def test_sparql_rejects_other_methods(client: TestClient, method: str) -> None:
    response = client.request(method.upper(), "/sparql", content=b"DROP ALL")
    assert response.status_code == 405


def test_query_parameter_is_required_and_get_has_no_side_effects(
    client: TestClient, query_runner: MemoryQueryRunner
) -> None:
    assert client.get("/sparql").status_code == 422
    assert query_runner.queries == []


def test_truncation_flag_matches_rows(
    loaded_store: MemoryStore, client: TestClient, settings: Settings
) -> None:
    settings.sparql_max_rows = 2
    response = _sparql(client, "SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
    assert response.status_code == 200
    assert response.headers["x-result-truncated"] == "true"
    assert len(response.json()["results"]["bindings"]) == 2
    exact = _sparql(client, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 2")
    assert exact.status_code == 200 and "x-result-truncated" not in exact.headers
    csv_response = _sparql(client, "SELECT ?s WHERE { ?s ?p ?o }", headers={"Accept": "text/csv"})
    assert csv_response.headers["x-result-truncated"] == "true"
    assert len(csv_response.text.strip().splitlines()) == 3  # cabecera + 2 filas
    construct = _sparql(client, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    assert construct.headers["x-result-truncated"] == "true"


def test_backend_errors_do_not_leak_internal_urls(
    client: TestClient, query_runner: MemoryQueryRunner, monkeypatch
) -> None:
    def broken(*_a, **_k):
        raise sparql_public.SparqlBackendError("Fuseki no responde")

    monkeypatch.setattr(query_runner, "run", broken)
    response = client.get("/sparql", params={"query": "ASK {}"})
    assert response.status_code == 503
    assert "fuseki.test" not in response.text and "3030" not in response.text


@pytest.mark.parametrize(
    "header",
    [
        {"X-Forwarded-For": "203.0.113.{n}"},
        {"X-Real-IP": "203.0.113.{n}"},
        {"Forwarded": "for=203.0.113.{n}"},
        {"X-Client-IP": "203.0.113.{n}"},
        {"True-Client-IP": "203.0.113.{n}"},
        {"CF-Connecting-IP": "203.0.113.{n}"},
        {"X-Forwarded-For": "203.0.113.{n}, 198.51.100.{n}"},
    ],
)
def test_rate_limit_is_not_bypassed_by_rotating_proxy_headers(
    client: TestClient, settings: Settings, header: dict[str, str]
) -> None:
    settings.sparql_rate_anon_per_min = 3
    statuses = []
    for n in range(1, 7):
        headers = {k: v.format(n=n) for k, v in header.items()}
        statuses.append(
            client.get("/sparql", params={"query": "ASK {}"}, headers=headers).status_code
        )
    assert statuses == [200, 200, 200, 429, 429, 429]


def test_rate_limit_applies_to_post_and_counts_rejected_queries(
    client: TestClient, settings: Settings
) -> None:
    settings.sparql_rate_anon_per_min = 3
    assert _sparql(client, "DROP ALL").status_code == 400
    assert _sparql(client, "SELECT * { SERVICE <http://x/> {?a ?b ?c} }").status_code == 400
    assert _sparql(client, "ASK {}").status_code == 200
    blocked = _sparql(client, "ASK {}")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1


def test_rate_limit_users_have_separate_buckets_and_anon_bucket_is_untouched(
    client: TestClient, settings: Settings, accounts
) -> None:
    settings.sparql_rate_anon_per_min = 1
    settings.sparql_rate_auth_per_min = 2
    for name in ("miembro", "editor"):
        for _ in range(2):
            assert (
                client.get(
                    "/sparql", params={"query": "ASK {}"}, headers=accounts[name]
                ).status_code
                == 200
            )
        assert (
            client.get("/sparql", params={"query": "ASK {}"}, headers=accounts[name]).status_code
            == 429
        )
    # El anónimo conserva su propio cupo.
    assert client.get("/sparql", params={"query": "ASK {}"}).status_code == 200


def test_invalid_or_revoked_token_is_401_and_not_a_free_anonymous_bucket(
    client: TestClient, settings: Settings, accounts, db: Session
) -> None:
    response = client.get(
        "/sparql", params={"query": "ASK {}"}, headers={"Authorization": "Bearer mala"}
    )
    assert response.status_code == 401
    user = db.scalars(select(User).where(User.username == "socia")).one()
    client.patch(f"/users/{user.id}", json={"is_active": False}, headers=accounts["admin"])
    revoked = client.get("/sparql", params={"query": "ASK {}"}, headers=accounts["miembro"])
    assert revoked.status_code == 401


def test_sparql_result_never_exposes_non_public_files_or_audit(
    loaded_store: MemoryStore, client: TestClient
) -> None:
    """El triplestore solo tiene metadatos: nada de usuarios, tokens ni rutas de disco."""
    response = _sparql(client, "SELECT * WHERE { ?s ?p ?o }", headers={"Accept": "text/csv"})
    body = response.text.lower()
    for forbidden in ("password", "jwt", "token", "/data/distributions", "sha256"):
        assert forbidden not in body


# ==========================================================================================
# 5. Login: bloqueo y revocación
# ==========================================================================================


def _token(client: TestClient, username: str, password: str):
    return client.post("/auth/token", data={"username": username, "password": password})


def test_fifth_failure_is_401_and_the_sixth_attempt_is_429(
    client: TestClient, make_user, settings: Settings
) -> None:
    make_user("ana")
    codes = [_token(client, "ana", "mala-contrasena-x").status_code for _ in range(6)]
    assert settings.login_max_failures == 5
    assert codes == [401, 401, 401, 401, 401, 429]


def test_lockout_has_decreasing_retry_after_and_ignores_correct_password(
    client: TestClient, make_user, settings: Settings
) -> None:
    make_user("ana")
    for _ in range(settings.login_max_failures):
        _token(client, "ana", "mala-contrasena-x")
    first = _token(client, "ana", DEFAULT_PASSWORD)
    assert first.status_code == 429
    retry = int(first.headers["retry-after"])
    assert settings.login_lockout_minutes * 60 - 5 <= retry <= settings.login_lockout_minutes * 60
    assert "access_token" not in first.text


def test_lockout_does_not_reveal_whether_the_user_exists(
    client: TestClient, make_user, settings: Settings
) -> None:
    make_user("ana")
    for name in ("ana", "no-existe"):
        for _ in range(settings.login_max_failures):
            _token(client, name, "mala-contrasena-x")
    real = _token(client, "ana", "mala-contrasena-x")
    ghost = _token(client, "no-existe", "mala-contrasena-x")
    assert real.status_code == ghost.status_code == 429
    assert real.json() == ghost.json()
    wrong = _token(client, "otro-inexistente", "x").json()
    known = _token(client, "ana", "x")
    assert known.status_code == 429  # sigue bloqueada
    fresh_wrong = _token(client, "tampoco", "x")
    assert fresh_wrong.json() == wrong


def test_lockout_of_one_user_does_not_lock_another(
    client: TestClient, make_user, settings: Settings
) -> None:
    make_user("ana")
    make_user("beto")
    for _ in range(settings.login_max_failures):
        _token(client, "ana", "mala-contrasena-x")
    assert _token(client, "ana", DEFAULT_PASSWORD).status_code == 429
    assert _token(client, "beto", DEFAULT_PASSWORD).status_code == 200


def test_username_variations_cannot_dodge_the_counter(
    client: TestClient, make_user, settings: Settings
) -> None:
    make_user("ana")
    variants = ["ana", "ANA", " ana", "ana ", "Ana", "aNa", "ana", "ANA", "ana"]
    for name in variants[: settings.login_max_failures]:
        _token(client, name, "mala-contrasena-x")
    assert _token(client, "ana", DEFAULT_PASSWORD).status_code == 429


def test_huge_username_and_control_chars_do_not_break_login_or_audit(
    client: TestClient, db: Session
) -> None:
    response = _token(client, "x" * 20_000 + "\x00\x1b[31m\r\nfalso", "mala-contrasena-x")
    assert response.status_code in (401, 422)
    for event in db.scalars(select(AuditEvent)):
        for value in (event.actor_username, event.target_username):
            assert value is None or (len(value) <= 64 and value.isprintable())
        assert "falso" not in json.dumps(event.details) or len(json.dumps(event.details)) < 200


def test_revoked_after_deactivation_for_every_protected_surface(
    client: TestClient, published, accounts, db: Session
) -> None:
    user = db.scalars(select(User).where(User.username == "socia")).one()
    upload(client, published, "restringida", CSV)
    client.patch(f"/users/{user.id}", json={"is_active": False}, headers=accounts["admin"])
    old = accounts["miembro"]
    assert client.get("/auth/me", headers=old).status_code == 401
    assert client.get("/sparql/queries", headers=old).status_code == 401
    assert (
        client.post(
            "/sparql/queries", json={"title": "t", "query": "ASK {}"}, headers=old
        ).status_code
        == 401
    )
    assert client.post(LINK.format(dist="restringida"), headers=old).status_code == 401
    assert client.get(FILE.format(dist="restringida"), headers=old).status_code == 401
    # Ni siquiera con la contraseña correcta mientras esté de baja.
    assert _token(client, "socia", DEFAULT_PASSWORD).status_code == 401


def test_reactivation_gives_new_tokens_but_not_the_old_ones(
    client: TestClient, accounts, db: Session
) -> None:
    user = db.scalars(select(User).where(User.username == "socia")).one()
    admin = accounts["admin"]
    client.patch(f"/users/{user.id}", json={"is_active": False}, headers=admin)
    client.patch(f"/users/{user.id}", json={"is_active": True}, headers=admin)
    assert client.get("/auth/me", headers=accounts["miembro"]).status_code == 401
    fresh = _token(client, "socia", DEFAULT_PASSWORD)
    assert fresh.status_code == 200
    headers = {"Authorization": f"Bearer {fresh.json()['access_token']}"}
    assert client.get("/auth/me", headers=headers).status_code == 200


def test_role_downgrade_revokes_editor_token_for_upload(
    client: TestClient, published, accounts, db: Session
) -> None:
    editor = db.scalars(select(User).where(User.username == "editora")).one()
    client.patch(f"/users/{editor.id}", json={"role": "miembro"}, headers=accounts["admin"])
    assert _put(client, "abierta", accounts["editor"]).status_code == 401


# ==========================================================================================
# 6. Consultas guardadas
# ==========================================================================================

BODY = {"title": "Mía", "hint": "pista", "query": "ASK {}"}


def test_other_users_queries_are_invisible_even_for_admin(
    client: TestClient, accounts, db: Session
) -> None:
    created = client.post("/sparql/queries", json=BODY, headers=accounts["miembro"]).json()
    for who in ("editor", "admin"):
        listed = client.get("/sparql/queries", headers=accounts[who]).json()
        assert created["id"] not in [q["id"] for q in listed]
        assert (
            client.put(
                f"/sparql/queries/{created['id']}",
                json=BODY | {"title": "robada"},
                headers=accounts[who],
            ).status_code
            == 404
        )
        assert (
            client.delete(f"/sparql/queries/{created['id']}", headers=accounts[who]).status_code
            == 404
        )
    mine = client.get("/sparql/queries", headers=accounts["miembro"]).json()[-1]
    assert mine["title"] == "Mía"


def test_not_found_responses_are_identical_for_foreign_and_missing_queries(
    client: TestClient, accounts
) -> None:
    created = client.post("/sparql/queries", json=BODY, headers=accounts["miembro"]).json()
    foreign = client.delete(f"/sparql/queries/{created['id']}", headers=accounts["editor"])
    missing = client.delete(f"/sparql/queries/{uuid.uuid4()}", headers=accounts["editor"])
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize(
    "query_id",
    ["no-es-uuid", "1' OR '1'='1", "../../etc/passwd", "%00", "0" * 400, "mapeos", "ot-datasets"],
)
def test_query_id_garbage_is_404_not_500(client: TestClient, accounts, query_id: str) -> None:
    for call in (client.delete, client.put):
        kwargs = {"json": BODY} if call is client.put else {}
        response = call(f"/sparql/queries/{query_id}", headers=accounts["miembro"], **kwargs)
        assert response.status_code in (404, 405, 422), (query_id, response.status_code)


def test_anonymous_cannot_touch_saved_queries(client: TestClient, accounts) -> None:
    created = client.post("/sparql/queries", json=BODY, headers=accounts["miembro"]).json()
    assert client.post("/sparql/queries", json=BODY).status_code == 401
    assert client.put(f"/sparql/queries/{created['id']}", json=BODY).status_code == 401
    assert client.delete(f"/sparql/queries/{created['id']}").status_code == 401
    anonymous = client.get("/sparql/queries").json()
    assert all(q["kind"] == "reference" for q in anonymous)


def test_reference_queries_cannot_be_overwritten_or_shadowed(client: TestClient, accounts) -> None:
    before = client.get("/sparql/queries").json()
    client.post(
        "/sparql/queries",
        json=BODY | {"title": "Datasets clasificados en OT"},
        headers=accounts["miembro"],
    )
    after = client.get("/sparql/queries", headers=accounts["miembro"]).json()
    assert after[: len(before)] == before
    assert [q["kind"] for q in after[: len(before)]] == ["reference"] * len(before)


def test_saved_query_limit_is_per_user_and_freed_by_delete(
    client: TestClient, accounts, settings: Settings
) -> None:
    settings.saved_queries_max_per_user = 2
    first = client.post("/sparql/queries", json=BODY, headers=accounts["miembro"]).json()
    client.post("/sparql/queries", json=BODY, headers=accounts["miembro"])
    assert client.post("/sparql/queries", json=BODY, headers=accounts["miembro"]).status_code == 409
    # El cupo es personal: otro usuario no lo comparte.
    assert client.post("/sparql/queries", json=BODY, headers=accounts["editor"]).status_code == 201
    # PUT no crea filas nuevas.
    assert (
        client.put(
            f"/sparql/queries/{first['id']}", json=BODY, headers=accounts["miembro"]
        ).status_code
        == 200
    )
    assert client.post("/sparql/queries", json=BODY, headers=accounts["miembro"]).status_code == 409
    assert (
        client.delete(f"/sparql/queries/{first['id']}", headers=accounts["miembro"]).status_code
        == 204
    )
    assert client.post("/sparql/queries", json=BODY, headers=accounts["miembro"]).status_code == 201


def test_saving_is_never_executing(
    client: TestClient, accounts, query_runner: MemoryQueryRunner
) -> None:
    for text in ("DROP ALL", "SELECT * { SERVICE <http://x/> { ?a ?b ?c } }", "SELECT * { ?s ?p"):
        response = client.post(
            "/sparql/queries", json=BODY | {"query": text}, headers=accounts["miembro"]
        )
        assert response.status_code == 201
    assert query_runner.queries == []


def test_saved_query_with_markup_is_returned_as_json_data(client: TestClient, accounts) -> None:
    payload = BODY | {"title": "<script>alert(1)</script>", "hint": "<img src=x onerror=1>"}
    created = client.post("/sparql/queries", json=payload, headers=accounts["miembro"])
    assert created.status_code == 201
    listed = client.get("/sparql/queries", headers=accounts["miembro"])
    assert listed.headers["content-type"].startswith("application/json")
    assert listed.json()[-1]["title"] == "<script>alert(1)</script>"


def test_saved_queries_survive_in_audit_only_as_ids(
    client: TestClient, accounts, db: Session
) -> None:
    text = "SELECT * { ?s ?p ?o } # TEXTO-SECRETO-DE-LA-CONSULTA"
    created = client.post(
        "/sparql/queries",
        json=BODY | {"query": text, "title": "TITULO-PRIVADO"},
        headers=accounts["miembro"],
    ).json()
    client.put(
        f"/sparql/queries/{created['id']}",
        json=BODY | {"query": text, "title": "TITULO-PRIVADO"},
        headers=accounts["miembro"],
    )
    client.delete(f"/sparql/queries/{created['id']}", headers=accounts["miembro"])
    dump = _audit_dump(db)
    assert "TEXTO-SECRETO" not in dump and "TITULO-PRIVADO" not in dump


# ==========================================================================================
# 7. Auditoría sin secretos
# ==========================================================================================


def test_audit_has_no_passwords_tokens_secrets_or_query_text(
    client: TestClient, published, accounts, settings: Settings, db: Session, make_user
) -> None:
    password_probe = "contrasena-que-no-debe-verse-1"
    make_user("victima")
    _token(client, "victima", password_probe)
    _token(client, "victima\x00intento", password_probe)
    upload(client, published, "restringida", CSV)
    url = _link(client, accounts["miembro"])
    token = url.split("token=", 1)[1]
    assert client.get(url).status_code == 200
    access = accounts["miembro"]["Authorization"].split()[1]
    client.get(FILE.format(dist="restringida"), headers=accounts["miembro"])
    secret_query = "SELECT * { ?s ?p ?o } # CONSULTA-PRIVADA-123"
    _sparql(client, secret_query, headers=accounts["miembro"])
    client.post("/sparql/queries", json=BODY | {"query": secret_query}, headers=accounts["miembro"])
    client.post("/datasets/prueba/versions/1.0.0/fair", headers=published)
    dump = _audit_dump(db)
    for secret in (
        password_probe,
        DEFAULT_PASSWORD,
        token,
        access,
        settings.jwt_secret,
        "CONSULTA-PRIVADA",
        "Bearer",
        '"password"',
        "$argon2",
    ):
        assert secret not in dump, secret
    # Lo que sí debe estar.
    for action in (
        AuditAction.LOGIN_FAILURE,
        AuditAction.DISTRIBUTION_UPLOADED,
        AuditAction.DISTRIBUTION_DOWNLOADED,
        AuditAction.SAVED_QUERY_CREATED,
    ):
        assert action.value in dump, action


def test_download_audit_distinguishes_session_and_link_without_leaking_the_token(
    client: TestClient, published, member, db: Session
) -> None:
    upload(client, published, "restringida", CSV)
    client.get(FILE.format(dist="restringida"), headers=member)
    client.get(_link(client, member))
    rows = db.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.DISTRIBUTION_DOWNLOADED.value)
    ).all()
    assert sorted(r.details["via"] for r in rows) == ["enlace", "sesion"]
    assert all(set(r.details) <= {"storage_key", "via"} for r in rows)


# ==========================================================================================
# 8. 303 sin Accept (decisión 31)
# ==========================================================================================

FRONTEND = "http://localhost:5173"
BROWSER_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
)


@pytest.mark.parametrize(
    "path",
    [
        "/dataset/modbus-tcp-testbed",
        "/dataset/modbus-tcp-testbed/2.1.0",
        "/dataset/modbus-tcp-testbed/2.1.0/pcap",
        "/onto/itot",
        "/vocab/ot",
    ],
)
def test_browser_accept_and_empty_accept_are_303_with_trusted_location(
    vocab_store: MemoryStore, client: TestClient, path: str
) -> None:
    for accept in ("", BROWSER_ACCEPT, "text/html;q=0.9, */*;q=0.1"):
        response = client.get(path, headers={"Accept": accept}, follow_redirects=False)
        assert response.status_code == 303, (path, accept)
        assert response.headers["location"].startswith(FRONTEND + "/")
        assert "Vary" in response.headers or response.headers.get("vary")


def test_rdf_accept_wins_over_html_when_ranked_higher(
    vocab_store: MemoryStore, client: TestClient
) -> None:
    response = client.get(
        "/dataset/modbus-tcp-testbed",
        headers={"Accept": "text/turtle, text/html;q=0.5"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/turtle")


@pytest.mark.parametrize(
    "path",
    [
        "/dataset/%2f%2fevil.example",
        "/dataset/modbus-tcp-testbed/..%2f..%2fevil",
        "/dataset/modbus-tcp-testbed/2.1.0/%2f%2fevil.example",
        "/onto/%5c%5cevil.example",
        "/vocab/https:%2f%2fevil.example",
    ],
)
def test_303_cannot_be_turned_into_an_open_redirect(
    vocab_store: MemoryStore, client: TestClient, path: str
) -> None:
    response = client.get(path, headers={"Accept": ""}, follow_redirects=False)
    if response.status_code == 303:
        assert response.headers["location"].startswith(FRONTEND + "/")
        assert "evil" not in response.headers["location"].split("?")[0][len(FRONTEND) :]
    else:
        assert response.status_code in (404, 422)


# ==========================================================================================
# 9. Defectos abiertos de la fase 4 (xfail estricto; aviso cuando se corrijan)
# ==========================================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-G4-03: el ejecutor lee toda la respuesta de Fuseki (hasta MAX_RESPONSE_BYTES) antes "
        "de recortar a SPARQL_MAX_ROWS: un SELECT cuyo resultado supera ese tope da 400 en lugar "
        "de truncarse con X-Result-Truncated (backend/app/sparql_public.py, _read_json)"
    ),
)
def test_select_over_the_byte_cap_is_truncated_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    monkeypatch.setattr(sparql_public, "MAX_RESPONSE_BYTES", 4096)
    row = {"s": {"type": "uri", "value": "http://ejemplo.org/" + "x" * 100}}
    data = {"head": {"vars": ["s"]}, "results": {"bindings": [row] * 200}}  # ~25 KB > 4096
    query = sparql_public.validate("SELECT ?s WHERE { ?s ?p ?o }", BASE_URI)
    runner = sparql_public.FusekiQueryRunner(
        "http://fuseki.test:3030",
        "itot",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data)),
    )
    result = runner.run(query, max_rows=10, timeout=5)
    assert result.truncated and len(result.bindings) == 10


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-G4-02: uvicorn arranca con su log de acceso por defecto y escribe la URL completa "
        "del enlace de descarga, con su ?token= firmado (backend/docker-entrypoint.sh)"
    ),
)
def test_backend_entrypoint_does_not_log_signed_download_links() -> None:
    entrypoint = (REPO_SEMANTIC_DIR.parent / "backend" / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    command = next(line for line in entrypoint.splitlines() if line.startswith("exec uvicorn"))
    assert "--no-access-log" in command or "--log-config" in command
