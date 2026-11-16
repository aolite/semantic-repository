"""Puerta G4 · «FAIR y versiones», de extremo a extremo sobre Docker Compose con F-UJI.

Criterio de la puerta: con el entorno local, un dataset publicado tiene evaluación FAIR de
F-UJI visible en su ficha; una versión nueva se publica sin poder alterar las anteriores; un
miembro descarga una distribución restringida y un anónimo no; la consola SPARQL ejecuta
consultas públicas con límites y guarda consultas personales.

La evaluación FAIR es la real: F-UJI corre dentro del Compose (red interna ``fuji-net``) y
evalúa el dataset a través del backend. Nada de esto simula F-UJI.

Comparte el entorno de ``conftest.py`` con G1 a G3 y se ejecuta después. Crea sus propias
cuentas. Los defectos conocidos llevan ``xfail(strict=True)`` con su identificador
``QA-G4-NN``; ver ``tests/e2e/README.md``. La prueba de límites de frecuencia va la última
porque agota el cupo anónimo del minuto.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.parse

import pytest
from conftest import (
    REPO_ROOT,
    Account,
    Response,
    Stack,
    create_account,
    http,
)

FILES_DIR = REPO_ROOT / "semantic" / "data" / "sintetico" / "ficheros"
AR = "http://publications.europa.eu/resource/authority/access-right/"
IANA = "http://www.iana.org/assignments/media-types/"
TURTLE = {"Content-Type": "text/turtle"}
SPARQL_QUERY = {"Content-Type": "application/sparql-query"}
SYNTHETIC = {
    "ejemplos-adversarios-vision": "0.9.0",
    "hallazgos-auditorias-intrusion": "1.3.0",
    "modbus-tcp-testbed": "2.1.0",
}
FAIR_TIMEOUT_SECONDS = 600


# --- Utilidades ------------------------------------------------------------------------


def _json(response: Response) -> dict:
    return response.json()  # type: ignore[return-value]


def _detail(stack: Stack, slug: str, version: str | None = None) -> dict:
    query = f"?version={version}" if version else ""
    response = http("GET", f"{stack.api}/datasets/{slug}{query}")
    assert response.status == 200, response.text
    return _json(response)


def _fair(stack: Stack, slug: str, version: str | None = None) -> dict:
    return _detail(stack, slug, version)["version"]["fair"]


def _wait_fair(
    stack: Stack, slug: str, version: str, *, status: str = "done", min_evaluations: int = 0
) -> dict:
    """Espera (con sondeo) a que la ficha de la versión muestre la evaluación en ``status``."""
    deadline = time.monotonic() + FAIR_TIMEOUT_SECONDS
    fair: dict = {}
    while time.monotonic() < deadline:
        fair = _fair(stack, slug, version) or {}
        done = _count_evaluations(stack, slug, version, "done")
        if fair.get("status") == status and done >= min_evaluations:
            return fair
        if fair.get("status") == "failed" and status != "failed":
            pytest.fail(f"La evaluación de {slug} {version} falló: {fair}")
        time.sleep(3)
    pytest.fail(f"La evaluación de {slug} {version} no llegó a {status!r}: {fair}")


def _count_evaluations(stack: Stack, slug: str, version: str, status: str | None = None) -> int:
    uri = f"{stack.env['BASE_URI']}dataset/{slug}/{version}"
    where = f" and status = '{status}'" if status else ""
    rows = stack.psql(f"select count(*) from fair_evaluations where version_uri = '{uri}'{where}")
    return int(rows[0])


def _audit(stack: Stack, action: str) -> list[dict]:
    return [
        json.loads(line)
        for line in stack.psql(
            f"select row_to_json(a) from audit_events a where a.action = '{action}' order by a.id"
        )
    ]


def _multipart(data: bytes) -> tuple[bytes, dict[str, str]]:
    boundary = f"qa4{secrets.token_hex(8)}"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.bin"\r\n'
        "Content-Type: application/x-cliente\r\n\r\n"
    ).encode()
    body = head + data + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def _put_file(
    stack: Stack, slug: str, version: str, dist: str, data: bytes, token: str | None
) -> Response:
    body, headers = _multipart(data)
    return http(
        "PUT",
        f"{stack.api}/datasets/{slug}/versions/{version}/distributions/{dist}/file",
        raw_body=body,
        headers=headers,
        token=token,
    )


def _file_url(stack: Stack, slug: str, version: str, dist: str) -> str:
    return f"{stack.api}/dataset/{slug}/{version}/{dist}/fichero"


def _link(stack: Stack, slug: str, version: str, dist: str, token: str | None) -> Response:
    return http(
        "POST",
        f"{stack.api}/datasets/{slug}/versions/{version}/distributions/{dist}/download-link",
        token=token,
    )


def _series_ttl(slug: str, versions: dict[str, dict]) -> str:
    """Serie de prueba con las versiones dadas (``{versión: {titulo, access, dists}}``)."""
    last = list(versions)[-1]
    out = [
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
        "@prefix dct:  <http://purl.org/dc/terms/> .",
        f"<dataset/{slug}> a dcat:DatasetSeries ; dct:type <vocab/tipo-dataset/sintetico> ;",
        f'    dct:title "Serie G4 {slug}"@es ; dct:description "Creada por la e2e de G4."@es ;',
        f"    dcat:last <dataset/{slug}/{last}> .",
    ]
    previous = None
    for version, spec in versions.items():
        dists = spec.get("dists", {"abierta": "PUBLIC"})
        links = ", ".join(f"<dataset/{slug}/{version}/{d}>" for d in dists)
        out += [
            f"<dataset/{slug}/{version}> a dcat:Dataset ; dct:type <vocab/tipo-dataset/sintetico> ;",
            f'    dct:title "{spec.get("titulo", "Versión " + version)}"@es ;',
            '    dct:description "Creada por la e2e de G4."@es ;',
            f'    dcat:version "{version}" ; dcat:inSeries <dataset/{slug}> ;',
            f"    dct:accessRights <{AR}{spec.get('access', 'PUBLIC')}> ;",
            "    dcat:theme <vocab/ot/modbus-tcp> ;",
        ]
        if previous:
            out.append(f"    dcat:previousVersion <dataset/{slug}/{previous}> ;")
        out.append(f"    dcat:distribution {links} .")
        for dist, access in dists.items():
            rights = f"dct:accessRights <{AR}{access}> ;" if access else ""
            out += [
                f"<dataset/{slug}/{version}/{dist}> a dcat:Distribution ; {rights}",
                f"    dcat:mediaType <{IANA}text/csv> ;",
                f"    dcat:accessURL <dataset/{slug}/{version}/{dist}> .",
            ]
        previous = version
    return "\n".join(out) + "\n"


def _publish(stack: Stack, body: str, token: str | None) -> Response:
    return http(
        "POST", f"{stack.api}/datasets", raw_body=body.encode(), headers=TURTLE, token=token
    )


def _sparql(stack: Stack, query: str, *, token: str | None = None, **headers: str) -> Response:
    return http(
        "POST",
        f"{stack.api}/sparql",
        raw_body=query.encode(),
        headers=SPARQL_QUERY | headers,
        token=token,
    )


def _forged_download_token(stack: Stack, storage_key: str, user_id: str, *, exp_in: int) -> str:
    """Enlace de descarga firmado a mano con el ``JWT_SECRET`` del entorno (HS256)."""

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(
        json.dumps(
            {
                "aud": "itot-download",
                "sub": user_id,
                "key": storage_key,
                "jti": secrets.token_hex(16),
                "iat": now,
                "exp": now + exp_in,
            }
        ).encode()
    )
    signature = hmac.new(
        stack.env["JWT_SECRET"].encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{b64(signature)}"


# --- Fixtures --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def g4_member(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "miembro")


@pytest.fixture(scope="module")
def g4_other_member(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "miembro")


@pytest.fixture(scope="module")
def g4_editor(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "editor")


@pytest.fixture(scope="module")
def loaded(stack: Stack) -> str:
    """``load-semantic`` (idempotente): datos sintéticos, ficheros y FAIR encolado."""
    result = stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=600
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def evaluated(stack: Stack, loaded: str) -> dict[str, dict]:
    """Esperas a que F-UJI termine la versión actual de los tres datasets sintéticos."""
    return {slug: _wait_fair(stack, slug, version) for slug, version in SYNTHETIC.items()}


@pytest.fixture(scope="module")
def series(stack: Stack, loaded: str, g4_editor: Account) -> dict:
    """Serie nueva con versión 1.0.0 (PUBLIC, RESTRICTED y NON_PUBLIC), publicada por un editor."""
    slug = f"e2e-g4-{secrets.token_hex(4)}"
    dists = {"abierta": "PUBLIC", "restringida": "RESTRICTED", "defensa": "NON_PUBLIC"}
    versions = {"1.0.0": {"access": "RESTRICTED", "dists": dists}}
    response = _publish(stack, _series_ttl(slug, versions), g4_editor.token)
    assert response.status == 201, response.text
    return {"slug": slug, "versions": versions}


# --- 1. Entorno de la fase 4 -----------------------------------------------------------


def test_los_servicios_de_la_fase_4_estan_sanos_y_fuji_no_se_publica(stack: Stack) -> None:
    result = stack.compose("ps", "--all", "--format", "json")
    assert result.returncode == 0, result.stderr
    text = result.stdout.strip()
    rows = json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines()]
    health = {row["Service"]: row["Health"] for row in rows}
    assert health == {
        name: "healthy" for name in ("postgres", "fuseki", "fuji", "backend", "frontend")
    }
    fuji = next(row for row in rows if row["Service"] == "fuji")
    assert not [p for p in fuji.get("Publishers") or [] if p.get("PublishedPort")], fuji


def test_fuji_no_tiene_salida_a_internet(stack: Stack) -> None:
    """F-UJI corre en una red interna: ni internet ni resolución de nombres externos."""
    script = (
        "import sys, urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('https://example.com/', timeout=5)\n"
        "except Exception:\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    result = stack.compose("exec", "-T", "fuji", "python3", "-c", script, timeout=60)
    assert result.returncode == 0, "F-UJI ha podido salir a internet"


def test_fuseki_el_usuario_backend_escribe_y_admin_administra(stack: Stack) -> None:
    """Decisión 32: usuario propio del backend; las contraseñas no son intercambiables."""

    def update(user: str | None, password: str | None, graph: str) -> int:
        headers = {"Content-Type": "application/sparql-update"}
        if user:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return http(
            "POST",
            f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/update",
            raw_body=f"INSERT DATA {{ GRAPH <urn:qa:g4:{graph}> {{ <urn:a> <urn:b> <urn:c> }} }}".encode(),
            headers=headers,
        ).status

    backend, admin_pwd = stack.env["FUSEKI_BACKEND_PASSWORD"], stack.env["FUSEKI_ADMIN_PASSWORD"]
    try:
        assert update("backend", backend, "ok") == 204
        assert update(None, None, "anonimo") == 401
        assert update("backend", stack.example_env["FUSEKI_BACKEND_PASSWORD"], "ejemplo") == 401
        assert update("backend", admin_pwd, "cruzada") == 401
        assert update("admin", backend, "cruzada2") == 401
    finally:
        clear = base64.b64encode(f"backend:{backend}".encode()).decode()
        http(
            "POST",
            f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/update",
            raw_body=b"CLEAR GRAPH <urn:qa:g4:ok>",
            headers={
                "Content-Type": "application/sparql-update",
                "Authorization": f"Basic {clear}",
            },
        )
    basic = base64.b64encode(f"backend:{backend}".encode()).decode()
    admin_api = http(
        "GET", f"{stack.fuseki}/$/datasets", headers={"Authorization": f"Basic {basic}"}
    )
    assert admin_api.status == 403  # el usuario backend no administra Fuseki


# --- 2. FAIR con F-UJI real ------------------------------------------------------------


def test_cada_dataset_publicado_tiene_evaluacion_fair_visible_en_su_ficha(
    stack: Stack, evaluated: dict[str, dict]
) -> None:
    for slug, version in SYNTHETIC.items():
        fair = _fair(stack, slug)
        assert fair["status"] == "done", (slug, fair)
        for key in ("total", "findable", "accessible", "interoperable", "reusable"):
            assert isinstance(fair[key], int | float) and 0 <= fair[key] <= 100, (slug, key)
        assert fair["evaluator"].startswith("F-UJI"), fair
        assert fair["evaluated_at"] and fair["maturity"] is not None
        assert fair["report_url"] == f"/datasets/{slug}/versions/{version}/fair/report"
        # El catálogo repite el total en la tarjeta («FAIR {n}»).
        cards = _json(http("GET", f"{stack.api}/datasets?page_size=100"))["items"]
        card = next(c for c in cards if c["slug"] == slug)
        assert card["fair_total"] == fair["total"]


def test_las_puntuaciones_salen_solo_del_informe_de_fuji(
    stack: Stack, evaluated: dict[str, dict]
) -> None:
    """Nada inventado ni redondeado: la ficha repite el resumen del informe de F-UJI."""
    for slug, version in SYNTHETIC.items():
        fair = evaluated[slug]
        report = http("GET", f"{stack.api}{fair['report_url']}")
        assert report.status == 200, report.text
        assert report.headers["content-type"].startswith("application/json")
        data = _json(report)
        summary = data["summary"]
        percent = summary["score_percent"]
        assert fair["total"] == percent["FAIR"], slug
        assert fair["findable"] == percent["F"]
        assert fair["accessible"] == percent["A"]
        assert fair["interoperable"] == percent["I"]
        assert fair["reusable"] == percent["R"]
        assert fair["maturity"] == str(summary["maturity"]["FAIR"])
        assert data["software_version"] in fair["evaluator"]
        # A F-UJI se le pasa la URL base interna, no el dominio de BASE_URI.
        request = data["request"]
        assert request["object_identifier"] == (
            f"{stack.example_env['FAIR_TARGET_BASE_URL']}dataset/{slug}/{version}"
        )
        assert request["use_datacite"] is False
        # La evaluación es completa: F-UJI ha aplicado sus pruebas, no un resultado vacío.
        assert data["total_metrics"] == len(data["results"]) >= 15


def test_la_ficha_de_cada_version_antigua_tiene_su_propia_evaluacion(
    stack: Stack, evaluated: dict[str, dict]
) -> None:
    for version in ("1.0.0", "2.0.0", "2.1.0"):
        fair = _wait_fair(stack, "modbus-tcp-testbed", version)
        assert fair["report_url"].endswith(f"/versions/{version}/fair/report")
    assert (
        http("GET", f"{stack.api}/datasets/modbus-tcp-testbed/versions/9.9.9/fair/report").status
        == 404
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-G4-01: F-UJI no llega a los metadatos. Pide /dataset/{slug}/{version} con "
        "`Accept: text/html, */*` y recibe el 303 al frontend (FRONTEND_BASE_URL, que no "
        "resuelve desde fuji-net: connection refused); y el respaldo por "
        "SPARQL envía `DESCRIBE <None>` con `Accept: application/rdf+xml` (406). "
        "Puntuación real: 8.33 sobre 100 frente a 52.08 si se le da la URL del RDF."
    ),
)
def test_fuji_lee_los_metadatos_del_dataset_pese_al_303(
    stack: Stack, evaluated: dict[str, dict]
) -> None:
    data = _json(http("GET", f"{stack.api}{evaluated['modbus-tcp-testbed']['report_url']}"))
    assert data["resolved_url"] not in (None, "", "not defined")
    assert data["harvested_metadata"], "F-UJI no ha recogido ningún metadato"
    assert evaluated["modbus-tcp-testbed"]["total"] > 25


def test_la_puntuacion_real_de_fuji_queda_anotada(
    stack: Stack, evaluated: dict[str, dict], capsys: pytest.CaptureFixture[str]
) -> None:
    """Deja en la salida la puntuación real obtenida (``pytest -s`` o el informe)."""
    for slug, fair in evaluated.items():
        line = (
            f"F-UJI {fair['evaluator']} · {slug}: total={fair['total']} F={fair['findable']} "
            f"A={fair['accessible']} I={fair['interoperable']} R={fair['reusable']} "
            f"madurez={fair['maturity']}"
        )
        with capsys.disabled():
            print(f"\n{line}")
        assert fair["status"] == "done"


def test_solo_el_editor_reevalua_y_queda_auditado(
    stack: Stack, evaluated: dict[str, dict], g4_member: Account, g4_editor: Account
) -> None:
    url = f"{stack.api}/datasets/hallazgos-auditorias-intrusion/versions/1.3.0/fair"
    assert http("POST", url).status == 401
    assert http("POST", url, token=g4_member.token).status == 403
    before = _count_evaluations(stack, "hallazgos-auditorias-intrusion", "1.3.0", "done")
    accepted = http("POST", url, token=g4_editor.token)
    assert accepted.status == 202, accepted.text
    assert _json(accepted)["status"] in ("pending", "running")
    _wait_fair(
        stack,
        "hallazgos-auditorias-intrusion",
        "1.3.0",
        min_evaluations=before + 1,
    )
    events = [e for e in _audit(stack, "fair_evaluated") if "hallazgos" in json.dumps(e["details"])]
    assert events and events[-1]["details"].get("status") == "done", events


def test_una_version_ya_evaluada_no_se_reevalua_al_volver_a_cargar(
    stack: Stack, evaluated: dict[str, dict]
) -> None:
    before = {v: _count_evaluations(stack, "modbus-tcp-testbed", v) for v in ("1.0.0", "2.0.0")}
    result = stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=600
    )
    assert result.returncode == 0, result.stdout + result.stderr
    time.sleep(15)  # más que FAIR_WORKER_POLL_SECONDS
    after = {v: _count_evaluations(stack, "modbus-tcp-testbed", v) for v in ("1.0.0", "2.0.0")}
    assert before == after


# --- 3. Versiones inmutables -----------------------------------------------------------


def test_una_version_nueva_se_publica_sin_alterar_las_anteriores(
    stack: Stack, series: dict, g4_editor: Account
) -> None:
    slug, versions = series["slug"], series["versions"]
    token = g4_editor.token
    old_fair = _wait_fair(stack, slug, "1.0.0")
    old_detail = _json(http("GET", f"{stack.api}/datasets/{slug}?version=1.0.0"))["version"]
    graph_before = http("GET", f"{stack.api}/datasets/{slug}/rdf?format=turtle&version=1.0.0").text

    # Republicar lo mismo: idempotente, no escribe y no vuelve a evaluar.
    same = _publish(stack, _series_ttl(slug, versions), token)
    assert same.status == 200, same.text
    assert _json(same)["changed"] is False
    assert _count_evaluations(stack, slug, "1.0.0") == 1

    # Una versión nueva se añade y se evalúa; la 1.0.0 sigue exactamente igual.
    bigger = {**versions, "1.1.0": {"access": "PUBLIC", "dists": {"abierta": "PUBLIC"}}}
    added = _publish(stack, _series_ttl(slug, bigger), token)
    assert added.status == 200, added.text
    assert _json(added)["changed"] is True
    new_fair = _wait_fair(stack, slug, "1.1.0")
    assert new_fair["report_url"].endswith("/1.1.0/fair/report")
    assert _json(http("GET", f"{stack.api}/datasets/{slug}"))["current_version"] == "1.1.0"
    now_detail = _json(http("GET", f"{stack.api}/datasets/{slug}?version=1.0.0"))["version"]
    assert now_detail == {**old_detail, "fair": now_detail["fair"]}
    assert now_detail["fair"] == old_fair
    assert (
        http("GET", f"{stack.api}/datasets/{slug}/rdf?format=turtle&version=1.0.0").text
        == graph_before
    )
    assert _count_evaluations(stack, slug, "1.0.0") == 1  # la antigua no se reevalúa sola


def test_alterar_una_version_publicada_da_409_y_no_escribe_nada(
    stack: Stack, series: dict, g4_editor: Account, g4_member: Account
) -> None:
    slug, versions = series["slug"], series["versions"]
    before_rdf = http("GET", f"{stack.api}/datasets/{slug}/rdf?format=turtle&version=1.0.0").text
    evaluations = _count_evaluations(stack, slug, "1.0.0")

    # La serie ya tiene la 1.1.0 (la añade la prueba anterior); se reenvía completa.
    full = {**versions, "1.1.0": {"access": "PUBLIC", "dists": {"abierta": "PUBLIC"}}}
    assert _publish(stack, _series_ttl(slug, full), g4_editor.token).status in (200, 201)
    events = len(_audit(stack, "dataset_published"))
    altered = {**full, "1.0.0": {**versions["1.0.0"], "titulo": "Título alterado"}}
    response = _publish(stack, _series_ttl(slug, altered), g4_editor.token)
    assert response.status == 409, response.text
    body = _json(response)
    assert body["kind"] == "version_immutable"
    assert [i["focus_node"] for i in body["issues"]] == [
        f"{stack.env['BASE_URI']}dataset/{slug}/1.0.0"
    ]
    # Cambiar accessRights para abrir una distribución tampoco vale.
    relaxed = {
        **full,
        "1.0.0": {
            **versions["1.0.0"],
            "dists": {"abierta": "PUBLIC", "restringida": "PUBLIC", "defensa": "NON_PUBLIC"},
        },
    }
    assert _publish(stack, _series_ttl(slug, relaxed), g4_editor.token).status == 409
    # Quitar una versión publicada.
    removed = {"1.1.0": {"access": "PUBLIC", "dists": {"abierta": "PUBLIC"}}}
    gone = _publish(stack, _series_ttl(slug, removed), g4_editor.token)
    assert gone.status == 409
    assert _json(gone)["kind"] == "version_removed"
    # Un miembro ni siquiera llega a la comprobación.
    assert _publish(stack, _series_ttl(slug, altered), g4_member.token).status == 403
    assert _publish(stack, _series_ttl(slug, altered), None).status == 401

    after_rdf = http("GET", f"{stack.api}/datasets/{slug}/rdf?format=turtle&version=1.0.0").text
    assert after_rdf == before_rdf
    assert len(_audit(stack, "dataset_published")) == events
    assert _count_evaluations(stack, slug, "1.0.0") == evaluations


def test_load_semantic_no_altera_las_versiones_sinteticas(stack: Stack, evaluated: dict) -> None:
    """Con los datos actuales de semantic/, recargar no da 409 ni cambia nada."""
    before = {slug: _fair(stack, slug) for slug in SYNTHETIC}
    result = stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=600
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "409" not in result.stdout and "inmutable" not in result.stdout.lower()
    assert {slug: _fair(stack, slug) for slug in SYNTHETIC} == before


# --- 4. Descargas ----------------------------------------------------------------------


def test_las_distribuciones_sinteticas_son_restringidas_y_la_que_falta_no_esta_disponible(
    stack: Stack, loaded: str
) -> None:
    detail = _detail(stack, "modbus-tcp-testbed")["version"]["distributions"]
    modes = {d["uri"].rsplit("/", 1)[1]: d["download"] for d in detail}
    assert modes == {"csv": "authenticated", "pcap": "authenticated", "parquet": "unavailable"}
    parquet = next(d for d in detail if d["uri"].endswith("/parquet"))
    assert parquet["download_url"] is None and parquet["byte_size"] is None
    for dist in detail:
        if dist["download"] == "authenticated":
            path = FILES_DIR / "modbus-tcp-testbed" / "2.1.0"
            real = next(path.glob(dist["uri"].rsplit("/", 1)[1] + ".*"))
            assert dist["byte_size"] == real.stat().st_size
            assert dist["sha256"] == hashlib.sha256(real.read_bytes()).hexdigest()


def test_un_miembro_descarga_la_restringida_con_enlace_firmado_y_un_anonimo_no(
    stack: Stack, loaded: str, g4_member: Account
) -> None:
    slug, version, dist = "modbus-tcp-testbed", "2.1.0", "csv"
    url = _file_url(stack, slug, version, dist)
    assert http("GET", url).status == 401
    assert http("GET", f"{url}?token=basura").status == 401
    assert (
        http(
            "POST",
            f"{stack.api}/datasets/{slug}/versions/{version}/distributions/{dist}/download-link",
        ).status
        == 401
    )

    link = _link(stack, slug, version, dist, g4_member.token)
    assert link.status == 200, link.text
    body = _json(link)
    assert body["url"].startswith(f"/dataset/{slug}/{version}/{dist}/fichero?token=")
    token = stack.remember("enlace de descarga", body["url"].split("token=", 1)[1])
    real = (FILES_DIR / slug / version / "csv.csv").read_bytes()
    first = http("GET", f"{stack.api}{body['url']}")
    assert first.status == 200
    assert first.content == real
    assert (
        first.headers["content-disposition"] == f'attachment; filename="{slug}-{version}-csv.csv"'
    )
    assert first.headers["content-length"] == str(len(real))
    assert first.headers["content-type"].startswith("text/csv")
    assert first.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in first.headers["cache-control"]
    # Un solo uso: el mismo enlace, con o sin otras cabeceras, ya no sirve.
    assert http("GET", f"{stack.api}{body['url']}").status == 401
    assert (
        http("GET", f"{stack.api}{body['url']}", headers={"X-Forwarded-For": "203.0.113.5"}).status
        == 401
    )
    # Con la cabecera Authorization también (sesión) y se audita con actor.
    session = http("GET", url, token=g4_member.token)
    assert session.status == 200 and session.content == real
    events = [
        e
        for e in _audit(stack, "distribution_downloaded")
        if e["actor_username"] == g4_member.username
    ]
    assert {e["details"]["via"] for e in events} >= {"enlace", "sesion"}
    assert all(e["details"]["storage_key"] == f"{slug}/{version}/{dist}" for e in events)
    assert token not in json.dumps(events)


def test_los_binarios_se_descargan_byte_a_byte(
    stack: Stack, loaded: str, g4_member: Account
) -> None:
    for slug, version, dist, name in (
        ("modbus-tcp-testbed", "2.1.0", "pcap", "pcap.pcap"),
        ("modbus-tcp-testbed", "1.0.0", "pcap", "pcap.pcap"),
        ("ejemplos-adversarios-vision", "0.9.0", "npz", "npz.npz"),
        ("hallazgos-auditorias-intrusion", "1.3.0", "rdf", "rdf.ttl"),
    ):
        response = http("GET", _file_url(stack, slug, version, dist), token=g4_member.token)
        assert response.status == 200, (slug, dist)
        assert response.content == (FILES_DIR / slug / version / name).read_bytes(), (slug, dist)
    # La NPZ del dataset de visión no declara dcat:mediaType.
    npz = http(
        "GET",
        _file_url(stack, "ejemplos-adversarios-vision", "0.9.0", "npz"),
        token=g4_member.token,
    )
    assert npz.headers["content-type"] == "application/octet-stream"


def test_la_distribucion_que_falta_da_404_y_no_hay_enlace(stack: Stack, g4_member: Account) -> None:
    url = _file_url(stack, "modbus-tcp-testbed", "2.1.0", "parquet")
    assert http("GET", url, token=g4_member.token).status == 404
    assert http("GET", url).status in (401, 404)
    assert _link(stack, "modbus-tcp-testbed", "2.1.0", "parquet", g4_member.token).status == 404


def test_enlaces_caducados_manipulados_o_de_otro_fichero_no_valen(
    stack: Stack, loaded: str, g4_member: Account, g4_other_member: Account
) -> None:
    slug, version = "modbus-tcp-testbed", "2.1.0"
    url = _file_url(stack, slug, version, "csv")
    key = f"{slug}/{version}/csv"
    me = _json(http("GET", f"{stack.api}/auth/me", token=g4_member.token))["id"]
    good = _forged_download_token(stack, key, me, exp_in=60)
    assert http("GET", f"{url}?token={good}").status == 200  # el control: la firma es la buena
    assert http("GET", f"{url}?token={good}").status == 401  # y se gasta
    expired = _forged_download_token(stack, key, me, exp_in=-30)
    assert http("GET", f"{url}?token={expired}").status == 401
    other_key = _forged_download_token(stack, f"{slug}/{version}/pcap", me, exp_in=60)
    assert http("GET", f"{url}?token={other_key}").status == 401
    head, payload, signature = good.split(".")
    assert http("GET", f"{url}?token={head}.{payload}.{signature[::-1]}").status == 401
    none_alg = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    assert http("GET", f"{url}?token={none_alg}.{payload}.").status == 401
    # El enlace emitido para el CSV no abre el PCAP.
    link = _json(_link(stack, slug, version, "csv", g4_other_member.token))["url"]
    token = link.split("token=", 1)[1]
    assert http("GET", f"{_file_url(stack, slug, version, 'pcap')}?token={token}").status == 401
    # Un token de acceso (JWT de sesión) no vale como enlace, ni al revés.
    assert http("GET", f"{url}?token={g4_member.token}").status == 401
    assert http("GET", f"{stack.api}/auth/me", token=token).status == 401


def test_el_enlace_firmado_caduca_de_verdad(stack: Stack, loaded: str, g4_member: Account) -> None:
    ttl = int(stack.env["DOWNLOAD_LINK_TTL_SECONDS"])
    link = _json(_link(stack, "modbus-tcp-testbed", "2.1.0", "csv", g4_member.token))
    time.sleep(ttl + 2)
    assert http("GET", f"{stack.api}{link['url']}").status == 401


@pytest.mark.parametrize(
    "path",
    [
        "/dataset/modbus-tcp-testbed/2.1.0/..%2f..%2f..%2fetc%2fpasswd/fichero",
        "/dataset/modbus-tcp-testbed/%2e%2e/csv/fichero",
        "/dataset/..%2f..%2fetc/2.1.0/csv/fichero",
        "/dataset/modbus-tcp-testbed/2.1.0/csv%00/fichero",
        "/dataset/modbus-tcp-testbed/2.1.0/%2fetc%2fpasswd/fichero",
        "/dataset/modbus-tcp-testbed/2.1.0/csv/..%2fpcap/fichero",
    ],
)
def test_path_traversal_en_la_descarga_no_sirve_nada(
    stack: Stack, loaded: str, g4_member: Account, path: str
) -> None:
    response = http("GET", f"{stack.api}{path}", token=g4_member.token)
    assert response.status in (404, 422), (path, response.status)
    assert "root:" not in response.text


def test_las_distribuciones_publicas_restringidas_y_de_defensa_de_una_serie_nueva(
    stack: Stack,
    series: dict,
    g4_editor: Account,
    g4_member: Account,
    admin: Account,
) -> None:
    slug = series["slug"]
    # Subida: solo editor o admin; la NON_PUBLIC nunca admite fichero.
    assert _put_file(stack, slug, "1.0.0", "abierta", b"a,b\n1,2\n", None).status == 401
    assert _put_file(stack, slug, "1.0.0", "abierta", b"a,b\n1,2\n", g4_member.token).status == 403
    defensa = _put_file(stack, slug, "1.0.0", "defensa", b"secreto", g4_editor.token)
    assert defensa.status == 409 and "non_public" in _json(defensa)["detail"]
    assert _put_file(stack, slug, "1.0.0", "defensa", b"secreto", admin.token).status == 409
    assert _put_file(stack, slug, "1.0.0", "no-existe", b"x", g4_editor.token).status == 404
    created = _put_file(stack, slug, "1.0.0", "abierta", b"a,b\n1,2\n", g4_editor.token)
    assert created.status == 201, created.text
    stored = _json(created)
    assert stored["sha256"] == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
    assert stored["media_type"] == "text/csv"  # el del RDF, no el del cliente
    # Idempotente con el mismo contenido; 409 con otro (inmutable).
    assert _put_file(stack, slug, "1.0.0", "abierta", b"a,b\n1,2\n", g4_editor.token).status == 200
    other = _put_file(stack, slug, "1.0.0", "abierta", b"otro", g4_editor.token)
    assert other.status == 409 and "file_exists" in _json(other)["detail"]
    assert _put_file(stack, slug, "1.0.0", "restringida", b"x,y\n3,4\n", admin.token).status == 201

    # PUBLIC: cualquiera, sin auditoría. RESTRICTED: solo con cuenta. NON_PUBLIC: nadie.
    before = len(_audit(stack, "distribution_downloaded"))
    assert http("GET", _file_url(stack, slug, "1.0.0", "abierta")).content == b"a,b\n1,2\n"
    assert len(_audit(stack, "distribution_downloaded")) == before
    assert http("GET", _file_url(stack, slug, "1.0.0", "restringida")).status == 401
    assert (
        http("GET", _file_url(stack, slug, "1.0.0", "restringida"), token=g4_member.token).status
        == 200
    )
    for token in (None, g4_member.token, g4_editor.token, admin.token):
        assert http("GET", _file_url(stack, slug, "1.0.0", "defensa"), token=token).status in (
            401,
            404,
        )
    assert _link(stack, slug, "1.0.0", "defensa", g4_member.token).status == 404
    modes = {
        d["uri"].rsplit("/", 1)[1]: d["download"]
        for d in _detail(stack, slug, "1.0.0")["version"]["distributions"]
    }
    assert modes == {"abierta": "open", "restringida": "authenticated", "defensa": "metadata_only"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-G4-05: subidas simultáneas del mismo fichero a la misma distribución dan 500 "
        "(IntegrityError al insertar dos veces `distribution_files.storage_key`) en lugar de "
        "201 la primera y 200 idempotente las demás"
    ),
)
def test_subidas_simultaneas_del_mismo_fichero_son_idempotentes(
    stack: Stack, g4_editor: Account
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    slug = f"e2e-g4-carrera-{secrets.token_hex(3)}"
    names = [f"d{n}" for n in range(8)]
    versions = {"1.0.0": {"access": "PUBLIC", "dists": {name: "PUBLIC" for name in names}}}
    assert _publish(stack, _series_ttl(slug, versions), g4_editor.token).status == 201
    data = b"a,b\n1,2\n"
    # Varias distribuciones y muchas subidas a la vez: la carrera no sale en todas las pasadas.
    with ThreadPoolExecutor(32) as pool:
        futures = {
            name: [
                pool.submit(_put_file, stack, slug, "1.0.0", name, data, g4_editor.token)
                for _ in range(10)
            ]
            for name in names
        }
        statuses = {name: [f.result().status for f in jobs] for name, jobs in futures.items()}
    flat = [status for values in statuses.values() for status in values]
    assert set(flat) <= {200, 201}, statuses
    assert all(values.count(201) == 1 for values in statuses.values()), statuses
    assert http("GET", _file_url(stack, slug, "1.0.0", "d0")).content == data


def test_dos_enlaces_simultaneos_del_mismo_token_solo_descargan_una_vez(
    stack: Stack, loaded: str, g4_member: Account
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    link = _json(_link(stack, "modbus-tcp-testbed", "2.1.0", "csv", g4_member.token))["url"]
    with ThreadPoolExecutor(20) as pool:
        statuses = list(pool.map(lambda _: http("GET", f"{stack.api}{link}").status, range(20)))
    assert statuses.count(200) == 1 and statuses.count(401) == 19, statuses


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-G4-02: el log de acceso de uvicorn escribe la URL completa del enlace de descarga, "
        "con su `?token=` firmado, en los logs del contenedor del backend"
    ),
)
def test_los_logs_no_contienen_los_enlaces_firmados(stack: Stack, loaded: str) -> None:
    logs = stack.compose("logs", "--no-color", "--no-log-prefix", "backend", timeout=120)
    text = logs.stdout + logs.stderr
    leaked = [name for name, secret in stack.sensitive.items() if secret in text]
    assert leaked == []


# --- 4 bis. Catálogo y búsqueda (decisiones 29, 30, 33 y 44) ---------------------------


def test_una_serie_publicada_por_la_api_cuelga_del_catalogo_rdf(
    stack: Stack, series: dict, g4_member: Account
) -> None:
    """QA-G2-05: ``<catálogo> dcat:dataset <serie>`` al publicar por la API."""
    base = stack.env["BASE_URI"]
    ask = f"ASK {{ <{base}catalogo> <http://www.w3.org/ns/dcat#dataset> <{base}dataset/{series['slug']}> }}"
    assert _json(_sparql(stack, ask, token=g4_member.token))["boolean"] is True
    # Y la recarga del catálogo (load-semantic) no la borra.
    result = stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=600
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _json(_sparql(stack, ask, token=g4_member.token))["boolean"] is True


def test_q_busca_en_la_uri_y_no_en_el_espacio_de_nombres(stack: Stack, loaded: str) -> None:
    """QA-G2-06 y QA-G3-11: ``q=itot`` ya no devuelve todo lo propio; la URI sí cuenta."""
    everything = _json(http("GET", f"{stack.api}/vocabularies?page_size=100"))
    total = everything["total"] if "total" in everything else len(everything["items"])
    itot = _json(http("GET", f"{stack.api}/vocabularies?q=itot"))
    found = itot["total"] if "total" in itot else len(itot["items"])
    assert 0 < found < total
    base = urllib.parse.quote(stack.env["BASE_URI"].split("//", 1)[1])
    assert _json(http("GET", f"{stack.api}/datasets?q={base}"))["total"] == 0  # BASE_URI no cuenta
    by_uri = _json(http("GET", f"{stack.api}/datasets?q=dataset/modbus-tcp"))
    assert [d["slug"] for d in by_uri["items"]] == ["modbus-tcp-testbed"]


def test_el_catalogo_se_pagina_con_page_y_page_size(stack: Stack, loaded: str) -> None:
    first = _json(http("GET", f"{stack.api}/datasets?page=1&page_size=2"))
    second = _json(http("GET", f"{stack.api}/datasets?page=2&page_size=2"))
    assert len(first["items"]) == 2 and first["page_size"] == 2 and first["total"] >= 3
    assert not {d["slug"] for d in first["items"]} & {d["slug"] for d in second["items"]}
    assert http("GET", f"{stack.api}/datasets?page_size=101").status == 422
    assert http("GET", f"{stack.api}/datasets?page=0").status == 422


def test_la_ontologia_itot_1_2_0_declara_ied_como_activo_industrial(
    stack: Stack, loaded: str, g4_other_member: Account
) -> None:
    """Decisión 44: ``IED ⊑ ActivoIndustrial`` solo en la 1.2.0."""
    base = stack.env["BASE_URI"]
    query = (
        f"ASK {{ GRAPH <{base}onto/itot/{{v}}> {{ <{base}onto/itot#IED> "
        f"<http://www.w3.org/2000/01/rdf-schema#subClassOf> <{base}onto/itot#ActivoIndustrial> }} }}"
    )
    assert (
        _json(_sparql(stack, query.replace("{v}", "1.2.0"), token=g4_other_member.token))["boolean"]
        is True
    )
    assert (
        _json(_sparql(stack, query.replace("{v}", "1.1.0"), token=g4_other_member.token))["boolean"]
        is False
    )
    detail = _json(http("GET", f"{stack.api}/ontologies/itot"))
    assert detail["metrics"]["classes"] == 13 and detail["metrics"]["logical_axioms"] == 8
    assert detail["consistency"]["consistent"] is True


# --- 5. Negociación de contenido (decisión 31) -----------------------------------------


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/dataset/modbus-tcp-testbed", "/datasets/modbus-tcp-testbed"),
        ("/dataset/modbus-tcp-testbed/2.1.0", "/datasets/modbus-tcp-testbed?version=2.1.0"),
        (
            "/dataset/modbus-tcp-testbed/2.1.0/csv",
            "/datasets/modbus-tcp-testbed?version=2.1.0#distribuciones",
        ),
        ("/onto/itot", "/ontologias/itot"),
        ("/vocab/ot", "/vocabularios/ot"),
    ],
)
def test_303_sin_accept_y_rdf_solo_con_accept_de_rdf(
    stack: Stack, loaded: str, path: str, target: str
) -> None:
    for headers in (
        {},
        {"Accept": "*/*"},
        {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
    ):
        see_other = http("GET", f"{stack.api}{path}", headers=headers, follow_redirects=False)
        assert see_other.status == 303, (path, headers)
        assert see_other.headers["location"] == f"{stack.frontend_origin}{target}"
    rdf = http("GET", f"{stack.api}{path}", headers={"Accept": "text/turtle"})
    assert rdf.status == 200 and rdf.headers["content-type"].startswith("text/turtle")
    jsonld = http("GET", f"{stack.api}{path}", headers={"Accept": "application/ld+json"})
    assert jsonld.status == 200 and ("@id" in jsonld.text or "@graph" in jsonld.text)


def test_la_uri_de_la_distribucion_sirve_su_rdf(stack: Stack, loaded: str) -> None:
    uri = f"{stack.api}/dataset/modbus-tcp-testbed/2.1.0/csv"
    turtle = http("GET", uri, headers={"Accept": "text/turtle"})
    assert turtle.status == 200
    assert f"{stack.env['BASE_URI']}dataset/modbus-tcp-testbed/2.1.0/csv" in turtle.text
    # El RDF publicado no cambia al subir ficheros: no lleva downloadURL ni tamaño.
    assert "downloadURL" not in turtle.text and "byteSize" not in turtle.text
    assert (
        http(
            "GET",
            f"{stack.api}/dataset/modbus-tcp-testbed/2.1.0/no-existe",
            headers={"Accept": "text/turtle"},
        ).status
        == 404
    )


# --- 6. Login (decisión 18) ------------------------------------------------------------


def test_el_bloqueo_de_login_responde_429_con_retry_after(stack: Stack, admin: Account) -> None:
    username = f"e2e-bloqueo-{secrets.token_hex(3)}"
    password = stack.remember("contraseña de la cuenta de bloqueo", secrets.token_urlsafe(24))
    created = http(
        "POST",
        f"{stack.api}/users",
        json_body={"username": username, "password": password, "role": "miembro"},
        token=admin.token,
    )
    assert created.status == 201, created.text
    bad = {"username": username, "password": "no-es-esta-contraseña"}
    maximum = int(stack.env["LOGIN_MAX_FAILURES"])
    for _ in range(maximum):
        assert http("POST", f"{stack.api}/auth/token", form=bad).status == 401
    locked = http(
        "POST", f"{stack.api}/auth/token", form={"username": username, "password": password}
    )
    assert locked.status == 429
    assert 1 <= int(locked.headers["retry-after"]) <= int(stack.env["LOGIN_LOCKOUT_MINUTES"]) * 60
    spoofed = http(
        "POST",
        f"{stack.api}/auth/token",
        form={"username": username, "password": password},
        headers={"X-Forwarded-For": "198.51.100.77"},
    )
    assert spoofed.status == 429
    # El bloqueo es por (usuario, IP): otras cuentas siguen entrando.
    other = http(
        "POST",
        f"{stack.api}/auth/token",
        form={"username": admin.username, "password": admin.password},
    )
    assert other.status == 200
    failures = [e for e in _audit(stack, "login_failure") if e["target_username"] == username]
    assert failures and all(password not in json.dumps(e) for e in failures)
    assert [e for e in _audit(stack, "login_locked") if e["target_username"] == username]


def test_una_baja_invalida_los_tokens_y_reactivar_no_los_revive(
    stack: Stack, admin: Account, loaded: str
) -> None:
    victim = create_account(stack, admin, "miembro")
    old = victim.token
    assert http("GET", f"{stack.api}/auth/me", token=old).status == 200
    patch = f"{stack.api}/users/{victim.id}"
    assert http("PATCH", patch, json_body={"is_active": False}, token=admin.token).status == 200
    assert http("GET", f"{stack.api}/auth/me", token=old).status == 401
    assert (
        http("GET", _file_url(stack, "modbus-tcp-testbed", "2.1.0", "csv"), token=old).status == 401
    )
    assert http("PATCH", patch, json_body={"is_active": True}, token=admin.token).status == 200
    assert http("GET", f"{stack.api}/auth/me", token=old).status == 401
    fresh = http(
        "POST",
        f"{stack.api}/auth/token",
        form={"username": victim.username, "password": victim.password},
    )
    assert fresh.status == 200
    assert http("GET", f"{stack.api}/auth/me", token=_json(fresh)["access_token"]).status == 200


# --- 7. Consola SPARQL: consultas, guardadas y límites ---------------------------------


def test_el_sparql_publico_responde_y_rechaza_lo_que_no_es_lectura(
    stack: Stack, loaded: str
) -> None:
    count = _sparql(
        stack,
        "PREFIX dcat: <http://www.w3.org/ns/dcat#> SELECT ?s WHERE { ?s a dcat:DatasetSeries }",
    )
    assert count.status == 200, count.text
    assert count.headers["content-type"].startswith("application/sparql-results+json")
    assert len(_json(count)["results"]["bindings"]) >= 3
    assert "x-result-truncated" not in count.headers
    assert _json(_sparql(stack, "ASK { ?s ?p ?o }"))["boolean"] is True
    csv = _sparql(
        stack,
        "SELECT ?s WHERE { ?s a <http://www.w3.org/ns/dcat#Dataset> } LIMIT 3",
        Accept="text/csv",
    )
    assert csv.status == 200 and csv.text.splitlines()[0] == "s"
    turtle = _sparql(stack, "CONSTRUCT { ?s a ?t } WHERE { ?s a ?t } LIMIT 5")
    assert turtle.status == 200 and turtle.headers["content-type"].startswith("text/turtle")
    ld = _sparql(
        stack, "DESCRIBE <" + stack.env["BASE_URI"] + "catalogo>", Accept="application/ld+json"
    )
    assert ld.status == 200
    # GET con ?query= también.
    get = http("GET", f"{stack.api}/sparql?query={urllib.parse.quote('ASK {}')}")
    assert get.status == 200


HOSTILE_QUERIES = [
    ("INSERT DATA { <urn:a> <urn:b> <urn:c> }", 400),
    ("DROP ALL", 400),
    ("CLEAR GRAPH <https://semantic.example.org/itot/catalogo>", 400),
    ("SELECT * { SERVICE <http://fuseki:3030/itot/sparql> { ?s ?p ?o } }", 400),
    ("SELECT * { SERVICE <http://169.254.169.254/latest/meta-data/> { ?s ?p ?o } }", 400),
    ("SELECT * FROM <http://ejemplo.org/g> { ?s ?p ?o }", 400),
    ("SELECT * FROM <file:///etc/passwd> { ?s ?p ?o }", 400),
    ("SELECT ?s WHERE { ?s ?p ", 400),
    ("SELECT * { ?s ?p ?o } #" + "x" * 21_000, 413),
]


def _triple_count(stack: Stack) -> int:
    response = http(
        "POST",
        f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/query",
        form={"query": "SELECT (COUNT(*) AS ?n) { GRAPH ?g { ?s ?p ?o } }"},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    return int(_json(response)["results"]["bindings"][0]["n"]["value"])


def test_el_sparql_publico_no_escribe_ni_federa_ni_lee_de_fuera(
    stack: Stack, loaded: str, g4_editor: Account
) -> None:
    """Va con sesión para no gastar el cupo anónimo; el cupo no cambia la validación."""
    before = _triple_count(stack)
    for query, status in HOSTILE_QUERIES:
        response = _sparql(stack, query, token=g4_editor.token)
        assert response.status == status, (query[:60], response.status, response.text)
        assert "Traceback" not in response.text and "fuseki" not in response.text.lower()
    # Y sin sesión, lo esencial (escritura, federación y FROM ajeno): el mismo rechazo.
    for query, status in (HOSTILE_QUERIES[0], HOSTILE_QUERIES[3], HOSTILE_QUERIES[5]):
        assert _sparql(stack, query).status == status
    assert _triple_count(stack) == before


def test_el_sparql_publico_no_se_cuelga_con_consultas_costosas_ni_enormes(
    stack: Stack, loaded: str, g4_editor: Account
) -> None:
    started = time.monotonic()
    slow = _sparql(
        stack,
        "SELECT (COUNT(*) AS ?n) WHERE { ?a ?b ?c . ?d ?e ?f . ?g ?h ?i . ?j ?k ?l }",
        token=g4_editor.token,
    )
    elapsed = time.monotonic() - started
    assert slow.status == 504, slow.text
    assert elapsed < int(stack.env["SPARQL_TIMEOUT_SECONDS"]) + 8
    # Truncado a SPARQL_MAX_ROWS con la cabecera.
    maximum = int(stack.env["SPARQL_MAX_ROWS"])
    big = _sparql(
        stack,
        f"SELECT * WHERE {{ ?a ?b ?c . ?d ?e ?f }} LIMIT {maximum + 2000}",
        token=g4_editor.token,
    )
    assert big.status == 200, big.text[:200]
    assert big.headers.get("x-result-truncated") == "true"
    assert len(_json(big)["results"]["bindings"]) == maximum
    # El servicio sigue sano tras las consultas costosas.
    assert http("GET", f"{stack.api}/health/ready").status == 200
    assert _json(_sparql(stack, "ASK {}", token=g4_editor.token))["boolean"] is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-G4-03: una consulta SELECT cuyo resultado supera 32 MB responde 400 «demasiado "
        "grande» en lugar de truncarse a SPARQL_MAX_ROWS con X-Result-Truncated: el ejecutor "
        "lee toda la respuesta de Fuseki antes de recortar las filas"
    ),
)
def test_un_select_enorme_se_trunca_en_vez_de_dar_400(
    stack: Stack, loaded: str, g4_editor: Account
) -> None:
    response = _sparql(stack, "SELECT * WHERE { ?a ?b ?c . ?d ?e ?f }", token=g4_editor.token)
    assert response.status == 200, response.text[:200]
    assert response.headers.get("x-result-truncated") == "true"


def test_las_consultas_de_referencia_son_publicas_y_se_ejecutan(
    stack: Stack, loaded: str, g4_other_member: Account
) -> None:
    listed = http("GET", f"{stack.api}/sparql/queries")
    assert listed.status == 200
    queries = _json(listed)
    assert [q["id"] for q in queries] == ["mapeos", "ot-datasets", "sin-definicion"]
    assert all(q["kind"] == "reference" and "{BASE_URI}" not in q["query"] for q in queries)
    for query in queries:
        response = _sparql(stack, query["query"], token=g4_other_member.token)
        assert response.status == 200, (query["id"], response.text)
    ot = _json(_sparql(stack, next(q for q in queries if q["id"] == "ot-datasets")["query"]))
    assert len(ot["results"]["bindings"]) >= 1


def test_un_miembro_guarda_una_consulta_personal_y_otro_no_la_ve(
    stack: Stack, loaded: str, g4_member: Account, g4_other_member: Account, admin: Account
) -> None:
    text = "SELECT * { ?s ?p ?o } # CONSULTA-PERSONAL-" + secrets.token_hex(4)
    body = {"title": "Mi consulta", "hint": "pista", "query": text}
    api = f"{stack.api}/sparql/queries"
    assert http("POST", api, json_body=body).status == 401
    created = http("POST", api, json_body=body, token=g4_member.token)
    assert created.status == 201, created.text
    item = _json(created)
    assert item["kind"] == "personal" and item["query"] == text and item["created_at"]
    mine = _json(http("GET", api, token=g4_member.token))
    assert [q["id"] for q in mine][-1] == item["id"]
    assert [q["kind"] for q in mine].count("reference") == 3
    for token in (None, g4_other_member.token, admin.token):
        others = _json(http("GET", api, token=token))
        assert item["id"] not in [q["id"] for q in others]
    # Otros usuarios (incluido un admin) no la modifican ni la borran: 404, no 403.
    for other in (g4_other_member.token, admin.token):
        assert http("PUT", f"{api}/{item['id']}", json_body=body, token=other).status == 404
        assert http("DELETE", f"{api}/{item['id']}", token=other).status == 404
    assert http("DELETE", f"{api}/ot-datasets", token=g4_member.token).status in (404, 405)
    changed = http(
        "PUT",
        f"{api}/{item['id']}",
        json_body={**body, "title": "Renombrada"},
        token=g4_member.token,
    )
    assert changed.status == 200 and _json(changed)["title"] == "Renombrada"
    # La auditoría guarda el id, nunca el texto de la consulta.
    audit = json.dumps(_audit(stack, "saved_query_created"))
    assert item["id"] in audit and text not in audit
    assert http("DELETE", f"{api}/{item['id']}", token=g4_member.token).status == 204
    assert text not in json.dumps(_audit(stack, "saved_query_deleted"))
    assert item["id"] not in [q["id"] for q in _json(http("GET", api, token=g4_member.token))]


def test_las_consultas_guardadas_tienen_limite_por_usuario(
    stack: Stack, loaded: str, admin: Account
) -> None:
    user = create_account(stack, admin, "miembro")
    api = f"{stack.api}/sparql/queries"
    maximum = int(stack.env["SAVED_QUERIES_MAX_PER_USER"])
    ids = []
    for index in range(maximum):
        response = http(
            "POST", api, json_body={"title": f"q{index}", "query": "ASK {}"}, token=user.token
        )
        assert response.status == 201, (index, response.text)
        ids.append(_json(response)["id"])
    assert (
        http(
            "POST", api, json_body={"title": "una más", "query": "ASK {}"}, token=user.token
        ).status
        == 409
    )
    # El cupo es personal.
    other = create_account(stack, admin, "miembro")
    assert (
        http("POST", api, json_body={"title": "mía", "query": "ASK {}"}, token=other.token).status
        == 201
    )
    assert http("DELETE", f"{api}/{ids[0]}", token=user.token).status == 204
    assert (
        http("POST", api, json_body={"title": "cabe", "query": "ASK {}"}, token=user.token).status
        == 201
    )


def test_la_auditoria_y_los_logs_no_contienen_secretos(stack: Stack, loaded: str) -> None:
    """Contraseñas, secretos de Fuseki y de F-UJI y JWT de las cuentas, en ningún sitio."""
    dump = "\n".join(stack.psql("select row_to_json(a) from audit_events a order by a.id"))
    logs = ""
    for service in ("backend", "fuseki", "fuji", "frontend", "postgres"):
        result = stack.compose("logs", "--no-color", "--no-log-prefix", service, timeout=120)
        logs += result.stdout + result.stderr
    fixed = {
        name: secret
        for name, secret in stack.sensitive.items()
        if name != "enlace de descarga"  # el enlace tiene su propia prueba (QA-G4-02)
    }
    for name, secret in fixed.items():
        assert secret not in dump, f"audit_events contiene {name}"
        assert secret not in logs, f"los logs contienen {name}"
    for name in ("FUSEKI_BACKEND_PASSWORD", "FUJI_PASSWORD", "FUSEKI_ADMIN_PASSWORD"):
        assert stack.env[name] not in dump + logs, name
    reports = stack.psql(
        "select count(*) from fair_evaluations where report::text like '%"
        + stack.env["FUJI_PASSWORD"]
        + "%'"
    )
    assert reports == ["0"]
    secrets_in_api = http("GET", f"{stack.api}/openapi.json").text
    assert stack.env["FUJI_PASSWORD"] not in secrets_in_api


# --- 8. Límites de frecuencia (al final: agota el cupo anónimo del minuto) --------------


def _wait_for_next_minute() -> None:
    """Los límites usan ventanas fijas de un minuto: se espera al inicio de la siguiente."""
    time.sleep(61 - (time.time() % 60))


def test_los_limites_de_frecuencia_del_sparql_por_ip_y_por_usuario(
    stack: Stack, loaded: str, g4_member: Account, g4_other_member: Account
) -> None:
    anon_limit = int(stack.env["SPARQL_RATE_ANON_PER_MIN"])
    auth_limit = int(stack.env["SPARQL_RATE_AUTH_PER_MIN"])
    _wait_for_next_minute()
    started = time.monotonic()
    statuses = [_sparql(stack, "ASK {}").status for _ in range(anon_limit + 3)]
    assert statuses[:anon_limit] == [200] * anon_limit
    assert statuses[anon_limit:] == [429] * 3
    blocked = _sparql(stack, "ASK {}")
    assert blocked.status == 429 and 1 <= int(blocked.headers["retry-after"]) <= 60
    # Rotar cabeceras de proxy no abre otro cupo: la IP es la de la conexión.
    for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded", "X-Client-IP"):
        value = "for=203.0.113.9" if header == "Forwarded" else "203.0.113.9"
        assert _sparql(stack, "ASK {}", **{header: value}).status == 429, header
    # Con sesión, el cupo es el del usuario y no el de la IP agotada.
    assert _sparql(stack, "ASK {}", token=g4_member.token).status == 200
    member_statuses = [
        _sparql(stack, "ASK {}", token=g4_member.token).status for _ in range(auth_limit + 2)
    ]
    assert member_statuses.count(429) >= 2 and member_statuses[0] == 200
    assert _sparql(stack, "ASK {}", token=g4_other_member.token).status == 200  # otro cupo
    assert time.monotonic() - started < 55, "la prueba cruzó una ventana de un minuto"
    # El resto de la API no se ve afectado.
    assert http("GET", f"{stack.api}/health/ready").status == 200
    assert re.fullmatch(r"\d+", blocked.headers["retry-after"])
