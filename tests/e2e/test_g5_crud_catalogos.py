"""Decisión 49 · CRUD de catálogos y datasets, de extremo a extremo sobre Docker Compose.

Contra el Compose real, con Fuseki real. Va después de G4 (por el nombre del fichero) y su
última prueba da de baja un dataset sintético, así que nada de lo que venga después puede
contar con él. Cubre: roles en cada endpoint nuevo, CRUD de catálogos y datasets, mover un
dataset, 410 (JSON, HTML y RDF) y 410 por prefijo, los dos 409, la exclusión de las bajas del
SPARQL público (con consultas hostiles), inyección en la construcción del RDF desde el JSON,
borrado de ficheros (también en datasets de defensa), auditoría, concurrencia y que
``load-semantic`` conserve lo hecho desde la aplicación.

Solo datos ficticios. Cómo lanzarlas: ``tests/e2e/README.md``.
"""

from __future__ import annotations

import json
import secrets
import threading
import urllib.parse

import pytest
from conftest import Account, Response, Stack, create_account, create_catalog, http

AR = "http://publications.europa.eu/resource/authority/access-right/"
IANA = "http://www.iana.org/assignments/media-types/"
TURTLE = {"Content-Type": "text/turtle"}
SPARQL_QUERY = {"Content-Type": "application/sparql-query"}
BROWSER_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
XSS_TITLE = "<script>alert(1)</script> \"comillas\" 'simples' & <b>x</b>"


# --- Utilidades ------------------------------------------------------------------------


def _slug(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3)}"


def _json(response: Response) -> dict:
    return response.json()  # type: ignore[return-value]


def _base(stack: Stack) -> str:
    return stack.env["BASE_URI"]


def _api(stack: Stack, method: str, path: str, token: str | None, body: object | None = None):
    return http(method, f"{stack.api}{path}", json_body=body, token=token)


def _catalog(stack: Stack, token: str | None, slug: str, title: str = "Catálogo ficticio"):
    return create_catalog(stack, token, slug, title)


def _dataset(
    stack: Stack, token: str | None, catalog: str, slug: str, title: str = "Dataset ficticio"
):
    return _api(
        stack,
        "POST",
        f"/catalogs/{catalog}/datasets",
        token,
        {"slug": slug, "title": title, "description": "Dataset de la prueba e2e de la 49."},
    )


def _series_ttl(slug: str, catalog: str | None, dists: dict[str, str], title: str = "Serie 49"):
    """Serie con una versión 1.0.0 y las distribuciones ``{dist: accessRights}``."""
    links = ", ".join(f"<dataset/{slug}/1.0.0/{d}>" for d in dists)
    out = [
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
        "@prefix dct:  <http://purl.org/dc/terms/> .",
    ]
    if catalog:
        out.append(f"<catalogo/{catalog}> dcat:dataset <dataset/{slug}> .")
    out += [
        f"<dataset/{slug}> a dcat:DatasetSeries ; dct:type <vocab/tipo-dataset/sintetico> ;",
        f'    dct:title "{title}"@es ; dct:description "Serie de la prueba de la 49."@es ;',
        f"    dcat:last <dataset/{slug}/1.0.0> .",
        f"<dataset/{slug}/1.0.0> a dcat:Dataset ; dct:type <vocab/tipo-dataset/sintetico> ;",
        f'    dct:title "{title}"@es ; dct:description "Serie de la prueba de la 49."@es ;',
        f'    dcat:version "1.0.0" ; dcat:inSeries <dataset/{slug}> ;',
        f"    dct:accessRights <{AR}PUBLIC> ; dcat:theme <vocab/ot/modbus-tcp> ;",
        f"    dcat:distribution {links} .",
    ]
    for dist, access in dists.items():
        out += [
            f"<dataset/{slug}/1.0.0/{dist}> a dcat:Distribution ; dct:accessRights <{AR}{access}> ;",
            f"    dcat:mediaType <{IANA}text/csv> ; dcat:accessURL <dataset/{slug}/1.0.0/{dist}> .",
        ]
    return "\n".join(out) + "\n"


def _publish(stack: Stack, ttl: str, token: str | None, query: str = "") -> Response:
    return http(
        "POST", f"{stack.api}/datasets{query}", raw_body=ttl.encode(), headers=TURTLE, token=token
    )


def _put_file(stack: Stack, slug: str, dist: str, data: bytes, token: str | None) -> Response:
    boundary = f"qa49{secrets.token_hex(8)}"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return http(
        "PUT",
        f"{stack.api}/datasets/{slug}/versions/1.0.0/distributions/{dist}/file",
        raw_body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        token=token,
    )


def _audit(stack: Stack, action: str) -> list[dict]:
    return [
        json.loads(line)
        for line in stack.psql(
            f"select row_to_json(a) from audit_events a where a.action = '{action}' order by a.id"
        )
    ]


def _load_semantic(stack: Stack) -> tuple[int, str]:
    result = stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=600
    )
    return result.returncode, result.stdout + result.stderr


def _fuseki(stack: Stack, query: str) -> dict:
    """Consulta directa a Fuseki (anónimo, publicado solo en 127.0.0.1): es el control que
    demuestra que la lápida está de verdad en el triplestore."""
    url = f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/query"
    response = http(
        "POST",
        url,
        form={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    return _json(response)


def _ask_graph(stack: Stack, graph: str, triple: str) -> bool:
    return _fuseki(stack, f"ASK {{ GRAPH <{graph}> {{ {triple} }} }}")["boolean"]  # type: ignore[return-value]


class _Sparql:
    """SPARQL público con una cuenta de miembro nueva cada 45 consultas (el límite es 60 por
    usuario y minuto; el anónimo, 30)."""

    def __init__(self, stack: Stack, admin: Account) -> None:
        self.stack, self.admin = stack, admin
        self.count = 0
        self.account = create_account(stack, admin, "miembro")

    def run(self, query: str, *, method: str = "POST", **headers: str) -> Response:
        if self.count >= 45:
            self.account = create_account(self.stack, self.admin, "miembro")
            self.count = 0
        self.count += 1
        if method == "GET":
            return http(
                "GET",
                f"{self.stack.api}/sparql?query={urllib.parse.quote(query)}",
                headers=headers,
                token=self.account.token,
            )
        return http(
            "POST",
            f"{self.stack.api}/sparql",
            raw_body=query.encode(),
            headers=SPARQL_QUERY | headers,
            token=self.account.token,
        )

    def rows(self, query: str) -> list[dict]:
        response = self.run(query)
        assert response.status == 200, response.text
        return _json(response)["results"]["bindings"]  # type: ignore[return-value]


# --- Fixtures --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crud_loaded(stack: Stack, admin: Account) -> str:
    code, output = _load_semantic(stack)
    assert code == 0, output
    return output


@pytest.fixture(scope="module")
def editor(stack: Stack, admin: Account, crud_loaded: str) -> Account:
    return create_account(stack, admin, "editor")


@pytest.fixture(scope="module")
def member(stack: Stack, admin: Account, crud_loaded: str) -> Account:
    return create_account(stack, admin, "miembro")


@pytest.fixture(scope="module")
def sparql(stack: Stack, admin: Account, crud_loaded: str) -> _Sparql:
    return _Sparql(stack, admin)


@pytest.fixture(scope="module")
def cat(stack: Stack, editor: Account) -> str:
    """Catálogo vivo para las pruebas que solo necesitan uno."""
    slug = _slug("cat")
    assert _catalog(stack, editor.token, slug).status == 201
    return slug


@pytest.fixture(scope="module")
def withdrawn(stack: Stack, editor: Account, cat: str) -> dict:
    """Un dataset con ficheros y un catálogo, ya dados de baja (para los 410 y los 409)."""
    slug, empty_cat = _slug("baja"), _slug("cbaja")
    assert _publish(stack, _series_ttl(slug, cat, {"csv": "PUBLIC"}), editor.token).status == 201
    # El título hostil entra por el JSON (en Turtle no cabrían las comillas sin escapar).
    assert _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"title": XSS_TITLE}).status == 200
    assert _put_file(stack, slug, "csv", b"a,b\n1,2\n", editor.token).status == 201
    assert _catalog(stack, editor.token, empty_cat, XSS_TITLE).status == 201
    assert _api(stack, "DELETE", f"/datasets/{slug}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/catalogs/{empty_cat}", editor.token).status == 204
    return {"slug": slug, "catalog": empty_cat, "cat": cat}


# --- 1. Roles en cada endpoint nuevo --------------------------------------------------

WRITE_ENDPOINTS = [
    ("POST", "/catalogs", {"slug": "x-rol", "title": "t", "description": "d", "publisher_name": "p"}),
    ("PATCH", "/catalogs/x-rol", {"title": "t"}),
    ("DELETE", "/catalogs/x-rol", None),
    ("POST", "/catalogs/x-rol/datasets", {"slug": "y-rol", "title": "t", "description": "d"}),
    ("PATCH", "/datasets/y-rol", {"title": "t"}),
    ("DELETE", "/datasets/y-rol", None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITE_ENDPOINTS)
def test_anonimo_401_y_miembro_403_en_cada_endpoint_nuevo(
    stack: Stack, member: Account, method: str, path: str, body: object | None
) -> None:
    assert _api(stack, method, path, None, body).status == 401
    assert _api(stack, method, path, member.token, body).status == 403
    # Token manipulado o con basura: 401, nunca un 403 ni un 404.
    forged = (member.token or "")[:-3] + "AAA"
    assert _api(stack, method, path, forged, body).status == 401
    assert _api(stack, method, path, "no-es-un-jwt", body).status == 401


def test_un_rechazo_por_rol_no_escribe_nada(stack: Stack, member: Account) -> None:
    slug = _slug("rol")
    before = len(stack.psql("select id from audit_events where action like 'catalog_%'"))
    assert _catalog(stack, member.token, slug).status == 403
    assert _catalog(stack, None, slug).status == 401
    assert http("GET", f"{stack.api}/catalogs/{slug}").status == 404
    assert len(stack.psql("select id from audit_events where action like 'catalog_%'")) == before


def test_la_lectura_de_catalogos_es_publica(stack: Stack, cat: str) -> None:
    listing = _json(http("GET", f"{stack.api}/catalogs"))
    slugs = {c["slug"] for c in listing["items"]}  # type: ignore[index]
    assert {"sintetico", cat} <= slugs
    assert http("GET", f"{stack.api}/catalogs/{cat}").status == 200


# --- 2. CRUD de catálogos por rol -------------------------------------------------------


def test_editor_y_admin_crean_editan_y_borran_catalogos(
    stack: Stack, admin: Account, editor: Account
) -> None:
    base = _base(stack)
    for actor in (editor, admin):
        slug = _slug("crud")
        created = _catalog(stack, actor.token, slug, "Título inicial")
        assert created.status == 201, created.text
        body = _json(created)
        assert body["uri"] == f"{base}catalogo/{slug}"
        assert body["title"] == "Título inicial" and body["datasets"] == []
        # El raíz lo agrupa con dcat:catalog (en su grafo).
        assert _ask_graph(
            stack, f"{base}catalogo", f"<{base}catalogo> <http://www.w3.org/ns/dcat#catalog> <{base}catalogo/{slug}>"
        )
        # Editar solo lo presente.
        patched = _api(stack, "PATCH", f"/catalogs/{slug}", actor.token, {"title": "Otro título"})
        assert patched.status == 200, patched.text
        assert _json(patched)["title"] == "Otro título"
        assert _json(patched)["description"] == body["description"]
        assert _json(patched)["publisher"] == body["publisher"]
        assert _api(stack, "PATCH", f"/catalogs/{slug}", actor.token, {"nope": 1}).status == 422
        assert _api(stack, "PATCH", f"/catalogs/{slug}", actor.token, {"title": ""}).status == 422
        assert _api(stack, "DELETE", f"/catalogs/{slug}", actor.token).status == 204
        assert http("GET", f"{stack.api}/catalogs/{slug}").status == 410
        assert slug not in {c["slug"] for c in _json(http("GET", f"{stack.api}/catalogs"))["items"]}  # type: ignore[index]
        # Y sale del raíz.
        assert not _ask_graph(
            stack, f"{base}catalogo", f"<{base}catalogo> <http://www.w3.org/ns/dcat#catalog> <{base}catalogo/{slug}>"
        )


def test_el_catalogo_raiz_es_fijo(stack: Stack, editor: Account, admin: Account) -> None:
    base = _base(stack)
    root = f"{base}catalogo"

    def root_state() -> list[tuple[str, str, str]]:
        rows = _fuseki(
            stack, f"SELECT ?p ?o WHERE {{ GRAPH <{root}> {{ <{root}> ?p ?o }} }}"
        )["results"]["bindings"]
        return sorted(
            (r["p"]["value"], r["o"]["value"], r["o"]["type"])
            for r in rows
            if r["p"]["value"] != "http://www.w3.org/ns/dcat#catalog"
        )

    before = root_state()
    assert before  # título, descripción, identificador…
    # No hay ruta para el raíz: la colección no admite PATCH ni DELETE.
    for actor in (editor, admin):
        assert _api(stack, "PATCH", "/catalogs", actor.token, {"title": "x"}).status in (404, 405)
        assert _api(stack, "DELETE", "/catalogs", actor.token).status in (404, 405)
    # Un catálogo con slug «catalogo» es catalogo/catalogo, distinto del raíz.
    sibling = _catalog(stack, editor.token, "catalogo")
    assert sibling.status in (201, 409), sibling.text
    if sibling.status == 201:
        assert _json(sibling)["uri"] == f"{base}catalogo/catalogo"
    assert _api(stack, "PATCH", "/catalogs/catalogo", editor.token, {"title": "Hermano"}).status == 200
    assert root_state() == before  # el raíz no ha cambiado
    # Publicar una serie colgando del raíz se rechaza (el raíz no lista series).
    slug = _slug("raiz")
    ttl = "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n<catalogo> dcat:dataset <dataset/" + slug + "> .\n"
    ttl += _series_ttl(slug, None, {"csv": "PUBLIC"})
    assert _publish(stack, ttl, editor.token).status == 422
    ttl = ttl.replace("<catalogo> dcat:dataset", "<catalogo> <http://purl.org/dc/terms/title> \"x\"@es ; dcat:dataset")
    assert _publish(stack, ttl, editor.token).status == 422
    assert http("GET", f"{stack.api}/datasets/{slug}").status == 404
    assert root_state() == before
    assert not _fuseki(
        stack, f"ASK {{ GRAPH <{root}> {{ <{root}> <http://www.w3.org/ns/dcat#dataset> ?x }} }}"
    )["boolean"]


def test_el_catalogo_con_datasets_da_409_con_su_lista(
    stack: Stack, editor: Account
) -> None:
    c, d = _slug("c409"), _slug("d409")
    assert _catalog(stack, editor.token, c).status == 201
    assert _dataset(stack, editor.token, c, d).status == 201
    response = _api(stack, "DELETE", f"/catalogs/{c}", editor.token)
    assert response.status == 409, response.text
    assert _json(response)["datasets"] == [f"{_base(stack)}dataset/{d}"]
    assert http("GET", f"{stack.api}/catalogs/{c}").status == 200  # sigue vivo
    assert _api(stack, "DELETE", f"/datasets/{d}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/catalogs/{c}", editor.token).status == 204


# --- 3. CRUD de datasets y mover de catálogo --------------------------------------------


def test_crear_editar_y_publicar_versiones_de_un_dataset(
    stack: Stack, admin: Account, editor: Account, cat: str
) -> None:
    base = _base(stack)
    for actor in (editor, admin):
        slug = _slug("ds")
        created = _dataset(stack, actor.token, cat, slug, "Título")
        assert created.status == 201, created.text
        assert _json(created)["uri"] == f"{base}dataset/{slug}"  # la URI no lleva el catálogo
        assert _dataset(stack, actor.token, cat, slug).status == 409  # slug en uso
        assert slug in [d["slug"] for d in _json(http("GET", f"{stack.api}/catalogs/{cat}"))["datasets"]]  # type: ignore[index]
        listed = _json(http("GET", f"{stack.api}/datasets?catalog={cat}&page_size=100"))
        assert slug in {i["slug"] for i in listed["items"]}  # type: ignore[index]
        patched = _api(stack, "PATCH", f"/datasets/{slug}", actor.token, {"title": "Nuevo"})
        assert patched.status == 200, patched.text
        assert _api(stack, "PATCH", f"/datasets/{slug}", actor.token, {"slug": "otro"}).status == 422
    # Un catálogo que no existe: 404; slug mal formado: 422.
    assert _dataset(stack, editor.token, _slug("nada"), _slug("d")).status == 404
    assert _dataset(stack, editor.token, cat, "Mal Slug").status == 422


def test_publicar_versiones_y_editar_no_toca_las_versiones(
    stack: Stack, editor: Account, cat: str
) -> None:
    slug = _slug("ver")
    assert _publish(stack, _series_ttl(slug, cat, {"csv": "PUBLIC"}), editor.token).status == 201
    before = http("GET", f"{stack.api}/datasets/{slug}/rdf?version=1.0.0&format=turtle")
    assert before.status == 200
    assert _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"title": "Cambiado"}).status == 200
    after = http("GET", f"{stack.api}/datasets/{slug}/rdf?version=1.0.0&format=turtle")
    assert after.text == before.text  # la versión publicada es inmutable (decisión 28)
    # Sin catálogo (ni triple ni ?catalog=): 422; con ?catalog=: 200 sin cambios.
    assert _publish(stack, _series_ttl(_slug("sin"), None, {"csv": "PUBLIC"}), editor.token).status == 422
    other = _slug("qs")
    assert _publish(stack, _series_ttl(other, None, {"csv": "PUBLIC"}), editor.token, f"?catalog={cat}").status == 201
    fresh = _slug("qs")
    assert _publish(stack, _series_ttl(fresh, None, {"csv": "PUBLIC"}), editor.token, "?catalog=no-existe").status == 422
    assert http("GET", f"{stack.api}/datasets/{fresh}").status == 404


def test_mover_un_dataset_de_catalogo(stack: Stack, editor: Account) -> None:
    base = _base(stack)
    a, b, slug = _slug("ma"), _slug("mb"), _slug("mv")
    for c in (a, b):
        assert _catalog(stack, editor.token, c).status == 201
    assert _publish(stack, _series_ttl(slug, a, {"csv": "PUBLIC"}), editor.token).status == 201
    rdf_before = http("GET", f"{stack.api}/datasets/{slug}/rdf?version=1.0.0&format=turtle").text
    member_triple = lambda c: f"<{base}catalogo/{c}> <http://www.w3.org/ns/dcat#dataset> <{base}dataset/{slug}>"  # noqa: E731
    assert _ask_graph(stack, f"{base}catalogo/{a}", member_triple(a))
    moved = _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"catalog": b})
    assert moved.status == 200, moved.text
    assert not _ask_graph(stack, f"{base}catalogo/{a}", member_triple(a))
    assert _ask_graph(stack, f"{base}catalogo/{b}", member_triple(b))
    assert _json(moved)["uri"] == f"{base}dataset/{slug}"
    assert http("GET", f"{stack.api}/datasets/{slug}/rdf?version=1.0.0&format=turtle").text == rdf_before
    assert [d["slug"] for d in _json(http("GET", f"{stack.api}/catalogs/{a}"))["datasets"]] == []  # type: ignore[index]
    assert [d["slug"] for d in _json(http("GET", f"{stack.api}/catalogs/{b}"))["datasets"]] == [slug]  # type: ignore[index]
    # Solo está en un catálogo: ni el RDF ni el JSON lo repiten.
    count = _fuseki(
        stack,
        f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH ?g {{ ?c <http://www.w3.org/ns/dcat#dataset> <{base}dataset/{slug}> }} }}",
    )["results"]["bindings"][0]["n"]["value"]  # type: ignore[index]
    assert count == "1"
    # Republicar con el catálogo de origen: 409 catalog_conflict (se mueve con PATCH).
    again = _publish(stack, _series_ttl(slug, a, {"csv": "PUBLIC"}), editor.token)
    assert again.status == 409, again.text
    assert _json(again).get("error") == "catalog_conflict" or "catalog_conflict" in again.text
    # Destino inexistente o dado de baja: 422.
    assert _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"catalog": _slug("zz")}).status == 422
    assert _api(stack, "DELETE", f"/catalogs/{a}", editor.token).status == 204
    assert _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"catalog": a}).status == 422


# --- 4. 410 y 410 por prefijo -----------------------------------------------------------


def test_410_json_en_la_api(stack: Stack, withdrawn: dict) -> None:
    slug, base = withdrawn["slug"], _base(stack)
    for path in (
        f"/datasets/{slug}",
        f"/datasets/{slug}?version=1.0.0",
        f"/datasets/{slug}/rdf?version=1.0.0",
        f"/datasets/{slug}/versions/1.0.0/fair/report",
        f"/catalogs/{withdrawn['catalog']}",
    ):
        response = http("GET", f"{stack.api}{path}")
        assert response.status == 410, f"{path}: {response.status} {response.text[:200]}"
        body = _json(response)
        assert body["uri"].startswith(base) and body["withdrawn_at"]  # type: ignore[index]
        assert body["title"] == XSS_TITLE  # el título es texto, sin tocar
    assert _json(http("GET", f"{stack.api}/datasets/{slug}"))["resource"] == "dataset"
    assert _json(http("GET", f"{stack.api}/catalogs/{withdrawn['catalog']}"))["resource"] == "catalog"
    # Lo que nunca existió sigue dando 404.
    assert http("GET", f"{stack.api}/datasets/{_slug('nunca')}").status == 404
    # Editar o borrar de nuevo lo dado de baja: 410 (no 404 ni 204).
    token = None
    assert _api(stack, "PATCH", f"/datasets/{slug}", token, {"title": "x"}).status == 401


def test_410_en_editar_y_borrar_lo_dado_de_baja(
    stack: Stack, editor: Account, withdrawn: dict
) -> None:
    slug, c = withdrawn["slug"], withdrawn["catalog"]
    assert _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"title": "x"}).status == 410
    assert _api(stack, "DELETE", f"/datasets/{slug}", editor.token).status == 410
    assert _api(stack, "PATCH", f"/catalogs/{c}", editor.token, {"title": "x"}).status == 410
    assert _api(stack, "DELETE", f"/catalogs/{c}", editor.token).status == 410
    assert _dataset(stack, editor.token, c, _slug("z")).status == 410


@pytest.mark.parametrize("accept", [None, "*/*", "text/html", BROWSER_ACCEPT])
def test_410_html_en_las_uris_persistentes(
    stack: Stack, withdrawn: dict, accept: str | None
) -> None:
    headers = {"Accept": accept} if accept else {}
    slug = withdrawn["slug"]
    for path in (
        f"/dataset/{slug}",
        f"/dataset/{slug}/1.0.0",
        f"/dataset/{slug}/1.0.0/csv",
        f"/dataset/{slug}/9.9.9",  # una versión que nunca existió: también por el prefijo
        f"/dataset/{slug}/1.0.0/csv/fichero",
        f"/catalogo/{withdrawn['catalog']}",
    ):
        response = http("GET", f"{stack.api}{path}", headers=headers, follow_redirects=False)
        assert response.status == 410, f"{path}: {response.status}"
        assert response.headers["content-type"].startswith("text/html")
        # Escapado: el título hostil no se interpreta como HTML.
        assert "<script>" not in response.text and "<b>x</b>" not in response.text
        assert "&lt;script&gt;" in response.text
        assert "location" not in response.headers


@pytest.mark.parametrize(
    ("accept", "marker"),
    [("text/turtle", "invalidatedAtTime"), ("application/ld+json", "invalidatedAtTime"),
     ("application/rdf+xml", "invalidatedAtTime")],
)
def test_410_rdf_es_la_lapida_y_nada_mas(
    stack: Stack, withdrawn: dict, accept: str, marker: str
) -> None:
    slug = withdrawn["slug"]
    for path in (f"/dataset/{slug}", f"/dataset/{slug}/1.0.0/csv", f"/catalogo/{withdrawn['catalog']}"):
        response = http("GET", f"{stack.api}{path}", headers={"Accept": accept}, follow_redirects=False)
        assert response.status == 410, f"{path}: {response.status}"
        assert marker in response.text and "Withdrawn" in response.text
        # Sin tipos DCAT ni descripción: solo la lápida (el @context de JSON-LD no cuenta).
        assert "DatasetSeries" not in response.text and "Catalog" not in response.text
        assert "Dataset de la prueba" not in response.text


def test_410_no_filtra_nada_del_recurso_borrado(stack: Stack, withdrawn: dict) -> None:
    slug = withdrawn["slug"]
    dump = http("GET", f"{stack.api}/dataset/{slug}", headers={"Accept": "text/turtle"}).text
    assert "Serie de la prueba de la 49" not in dump
    assert "modbus-tcp" not in dump
    # Fichero: la descarga también da 410 y no sirve contenido.
    response = http("GET", f"{stack.api}/dataset/{slug}/1.0.0/csv/fichero")
    assert response.status == 410 and b"a,b" not in response.content


# --- 5. Los dos 409 por slug --------------------------------------------------------------


def test_un_slug_dado_de_baja_no_se_reutiliza(
    stack: Stack, editor: Account, admin: Account, withdrawn: dict, cat: str
) -> None:
    slug, c = withdrawn["slug"], withdrawn["catalog"]
    assert _dataset(stack, editor.token, cat, slug).status == 409
    assert _catalog(stack, admin.token, c).status == 409
    response = _publish(stack, _series_ttl(slug, cat, {"csv": "PUBLIC"}), editor.token)
    assert response.status == 409 and "withdrawn" in response.text
    assert _publish(stack, _series_ttl(slug, None, {"csv": "PUBLIC"}), editor.token, f"?catalog={cat}").status == 409
    # Nada se ha escrito: sigue dando 410.
    assert http("GET", f"{stack.api}/datasets/{slug}").status == 410
    assert http("GET", f"{stack.api}/catalogs/{c}").status == 410


# --- 6. Las bajas no salen en el SPARQL público (Fuseki real) ----------------------------

PREFIXES = (
    "PREFIX prov: <http://www.w3.org/ns/prov#> PREFIX adms: <http://www.w3.org/ns/adms#> "
)


def _tombstone_triples(rows: list[dict]) -> bool:
    return bool(rows)


def test_control_la_lapida_existe_en_fuseki(stack: Stack, withdrawn: dict) -> None:
    """Sin este control, las pruebas de exclusión podrían pasar porque no hay lápida."""
    base = _base(stack)
    rows = _fuseki(
        stack,
        f"{PREFIXES} SELECT ?t WHERE {{ GRAPH <{base}bajas> {{ <{base}dataset/{withdrawn['slug']}> prov:invalidatedAtTime ?t }} }}",
    )["results"]["bindings"]
    assert len(rows) == 1
    # Y el grafo por defecto de Fuseki (unión) sí la ve: por eso el backend pasa los grafos.
    union = _fuseki(
        stack,
        f"{PREFIXES} SELECT ?t WHERE {{ <{base}dataset/{withdrawn['slug']}> prov:invalidatedAtTime ?t }}",
    )["results"]["bindings"]
    assert len(union) == 1
    # Y el grafo con el dataset ya no existe, ni su enlace desde el catálogo.
    assert not _fuseki(stack, f"ASK {{ GRAPH <{base}dataset/{withdrawn['slug']}> {{ ?s ?p ?o }} }}")["boolean"]


def _hostile_queries(base: str, uri: str, cat_uri: str) -> list[tuple[str, str]]:
    p = PREFIXES
    return [
        ("default", f"{p} SELECT ?t WHERE {{ <{uri}> prov:invalidatedAtTime ?t }}"),
        ("default-any", f"{p} SELECT ?s WHERE {{ ?s prov:invalidatedAtTime ?t }}"),
        ("estado", f"{p} SELECT ?s WHERE {{ ?s adms:status <http://purl.org/adms/status/Withdrawn> }}"),
        ("GRAPH ?g", f"{p} SELECT ?g WHERE {{ GRAPH ?g {{ ?s prov:invalidatedAtTime ?t }} }}"),
        ("GRAPH <bajas>", f"{p} SELECT ?s WHERE {{ GRAPH <{base}bajas> {{ ?s ?p ?o }} }}"),
        ("VALUES", f"{p} SELECT ?s WHERE {{ VALUES ?g {{ <{base}bajas> }} GRAPH ?g {{ ?s ?p ?o }} }}"),
        ("BIND", f"{p} SELECT ?s WHERE {{ BIND(<{base}bajas> AS ?g) GRAPH ?g {{ ?s ?p ?o }} }}"),
        ("FILTER", f"{p} SELECT ?s WHERE {{ GRAPH ?g {{ ?s ?p ?o }} FILTER(STR(?g) = \"{base}bajas\") }}"),
        ("STRSTARTS", f"{p} SELECT ?s WHERE {{ GRAPH ?g {{ ?s ?p ?o }} FILTER(STRENDS(STR(?g), \"/bajas\")) }}"),
        ("UNION", f"{p} SELECT ?s WHERE {{ {{ ?s prov:invalidatedAtTime ?t }} UNION {{ GRAPH ?g {{ ?s prov:invalidatedAtTime ?t }} }} }}"),
        ("subconsulta", f"{p} SELECT ?s WHERE {{ {{ SELECT ?s WHERE {{ GRAPH ?g {{ ?s prov:invalidatedAtTime ?t }} }} }} }}"),
        ("CONSTRUCT", f"{p} CONSTRUCT {{ ?s ?p ?o }} WHERE {{ ?s prov:invalidatedAtTime ?o . ?s ?p ?o }}"),
        ("DESCRIBE", f"DESCRIBE <{uri}>"),
        ("DESCRIBE catálogo", f"DESCRIBE <{cat_uri}>"),
        ("ASK", f"{p} ASK {{ ?s prov:invalidatedAtTime ?t }}"),
        ("ASK GRAPH", f"{p} ASK {{ GRAPH <{base}bajas> {{ ?s ?p ?o }} }}"),
        ("FROM published + GRAPH", f"{p} SELECT ?s FROM <{base}catalogo> WHERE {{ GRAPH <{base}bajas> {{ ?s ?p ?o }} }}"),
        ("FROM NAMED published + GRAPH ?g", f"{p} SELECT ?s FROM NAMED <{base}catalogo> WHERE {{ GRAPH ?g {{ ?s prov:invalidatedAtTime ?t }} }}"),
    ]


def _has_tombstone(response: Response, uri: str, cat_uri: str) -> bool:
    return "invalidatedAtTime" in response.text or "Withdrawn" in response.text or (
        response.status == 200 and '"bindings": []' not in response.text
        and '"bindings":[]' not in response.text
        and '"boolean": false' not in response.text
        and '"boolean":false' not in response.text
        and ("prov" in response.text or uri in response.text)
        and "bindings" in response.text
    )


def test_ninguna_consulta_publica_ve_las_lapidas(
    stack: Stack, sparql: _Sparql, withdrawn: dict
) -> None:
    base = _base(stack)
    uri = f"{base}dataset/{withdrawn['slug']}"
    cat_uri = f"{base}catalogo/{withdrawn['catalog']}"
    leaks = []
    for name, query in _hostile_queries(base, uri, cat_uri):
        for method in ("POST", "GET"):
            response = sparql.run(query, method=method)
            assert response.status in (200, 400), f"{name}: {response.status} {response.text[:200]}"
            if response.status == 200:
                body = response.text
                if "invalidatedAtTime" in body or "Withdrawn" in body or uri in body or cat_uri in body:
                    leaks.append((name, method, body[:300]))
                if '"boolean"' in body and '"boolean": true' in body.replace('":true', '": true'):
                    leaks.append((name, method, body[:300]))
                if "json" in response.headers.get("content-type", ""):
                    for row in (_json(response).get("results", {}) or {}).get("bindings", []):
                        leaks.append((name, method, str(row)[:200]))
                elif response.text.strip() and "@prefix" not in response.text[:0]:
                    # CONSTRUCT/DESCRIBE: Turtle con triples = fuga (un grafo vacío no tiene).
                    body_lines = [x for x in response.text.splitlines() if x.strip() and not x.startswith("@prefix")]
                    if body_lines:
                        leaks.append((name, method, response.text[:200]))
    assert leaks == []


@pytest.mark.parametrize("clause", ["FROM", "FROM NAMED"])
def test_from_hacia_las_bajas_da_400(stack: Stack, sparql: _Sparql, clause: str) -> None:
    base = _base(stack)
    response = sparql.run(f"SELECT * {clause} <{base}bajas> WHERE {{ ?s ?p ?o }}")
    assert response.status == 400, response.text
    assert sparql.run(f"SELECT * {clause} <{base}bajas> WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }}").status == 400
    assert sparql.run(f"ASK {clause} <{base}bajas> {{ ?s ?p ?o }}").status == 400
    # Con otro grafo publicado a la vez, sigue dando 400.
    assert sparql.run(f"SELECT * FROM <{base}catalogo> {clause} <{base}bajas> WHERE {{ ?s ?p ?o }}").status == 400


@pytest.mark.parametrize(
    "variant",
    ["{b}x/../bajas", "{b}./bajas", "{b}bajas%20", "{b}BAJAS", "{b}bajas#", "{b}bajas?x=1",
     "HTTPS://SEMANTIC.EXAMPLE.ORG/itot/bajas", "{b}%62ajas"],
)
def test_from_con_variantes_de_la_iri_de_las_bajas(
    stack: Stack, sparql: _Sparql, withdrawn: dict, variant: str
) -> None:
    """Da 400 o devuelve vacío, pero nunca la lápida."""
    base = _base(stack)
    target = variant.replace("{b}", base)
    for clause in ("FROM", "FROM NAMED"):
        response = sparql.run(f"SELECT * {clause} <{target}> WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }}")
        assert response.status in (200, 400), response.text[:200]
        assert "invalidatedAtTime" not in response.text
        assert withdrawn["slug"] not in response.text


def test_service_y_escritura_siguen_rechazados(stack: Stack, sparql: _Sparql) -> None:
    base = _base(stack)
    own = f"{stack.env['FUSEKI_URL']}/{stack.env['FUSEKI_DATASET']}/query"
    assert sparql.run(f"SELECT * WHERE {{ SERVICE <{own}> {{ GRAPH <{base}bajas> {{ ?s ?p ?o }} }} }}").status == 400
    assert sparql.run(f"SELECT * WHERE {{ GRAPH <{base}bajas> {{ SERVICE <{own}> {{ ?s ?p ?o }} }} }}").status == 400
    assert sparql.run(f"DROP GRAPH <{base}bajas>").status == 400
    assert sparql.run(f"CLEAR GRAPH <{base}bajas>").status == 400
    assert sparql.run(f"INSERT DATA {{ GRAPH <{base}bajas> {{ <{base}x> <{base}y> <{base}z> }} }}").status == 400
    assert sparql.run(f"DELETE WHERE {{ GRAPH <{base}bajas> {{ ?s ?p ?o }} }}").status == 400


def test_los_parametros_de_grafo_del_cliente_se_ignoran(
    stack: Stack, sparql: _Sparql, withdrawn: dict
) -> None:
    """El cliente no puede colar ``default-graph-uri`` ni ``named-graph-uri`` en el protocolo."""
    base = _base(stack)
    q = urllib.parse.quote("SELECT ?s WHERE { ?s ?p ?o } LIMIT 5")
    for extra in (
        f"&default-graph-uri={urllib.parse.quote(base + 'bajas')}",
        f"&named-graph-uri={urllib.parse.quote(base + 'bajas')}",
    ):
        response = http(
            "GET", f"{stack.api}/sparql?query={q}{extra}", token=sparql.account.token
        )
        assert response.status in (200, 400)
        assert "invalidatedAtTime" not in response.text and withdrawn["slug"] not in response.text
    form = {
        "query": f"SELECT ?s ?p ?o WHERE {{ GRAPH ?g {{ ?s ?p ?o }} FILTER(?p = <http://www.w3.org/ns/prov#invalidatedAtTime>) }}",
        "default-graph-uri": base + "bajas",
        "named-graph-uri": base + "bajas",
    }
    response = http("POST", f"{stack.api}/sparql", form=form, token=sparql.account.token)
    assert response.status in (200, 400)
    assert "invalidatedAtTime" not in response.text and '"value"' not in response.text.split("bindings")[-1]


def test_el_grafo_por_defecto_y_graph_siguen_viendo_lo_publicado(
    stack: Stack, sparql: _Sparql, cat: str
) -> None:
    """Control de que la exclusión no rompe el SPARQL: se ven catálogos y datasets."""
    base = _base(stack)
    graphs = {r["g"]["value"] for r in sparql.rows("SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }")}
    assert f"{base}bajas" not in graphs
    assert {f"{base}catalogo", f"{base}catalogo/sintetico", f"{base}catalogo/{cat}"} <= graphs
    assert any(g.startswith(f"{base}dataset/") for g in graphs)
    titles = sparql.rows(
        f"SELECT ?t WHERE {{ <{base}catalogo/sintetico> <http://purl.org/dc/terms/title> ?t }}"
    )
    assert titles
    both = sparql.rows(
        f"SELECT ?s WHERE {{ ?s a <http://www.w3.org/ns/dcat#DatasetSeries> }}"
    )
    assert len(both) >= 3
    # Con FROM a un grafo publicado funciona.
    assert sparql.run(f"SELECT * FROM <{base}catalogo/sintetico> WHERE {{ ?s ?p ?o }} LIMIT 1").status == 200


def test_un_dataset_dado_de_baja_sale_de_los_listados_y_del_sparql(
    stack: Stack, sparql: _Sparql, withdrawn: dict
) -> None:
    base = _base(stack)
    uri = f"{base}dataset/{withdrawn['slug']}"
    assert not sparql.rows(f"SELECT * WHERE {{ <{uri}> ?p ?o }}")
    assert not sparql.rows(f"SELECT * WHERE {{ ?s ?p <{uri}> }}")
    assert not sparql.rows(f"SELECT * WHERE {{ ?s ?p ?o FILTER(STRSTARTS(STR(?s), \"{uri}/\")) }}")
    listing = _json(http("GET", f"{stack.api}/datasets?page_size=100&q={withdrawn['slug']}"))
    assert listing["total"] == 0  # type: ignore[index]
    cats = _json(http("GET", f"{stack.api}/catalogs"))
    assert withdrawn["catalog"] not in {c["slug"] for c in cats["items"]}  # type: ignore[index]
    assert withdrawn["slug"] not in json.dumps(_json(http("GET", f"{stack.api}/catalogs/{withdrawn['cat']}")))


# --- 7. Inyección en la construcción del RDF desde el JSON -------------------------------

HOSTILE = [
    '" ; <http://purl.org/dc/terms/title> "inyectado',
    '"""\n<http://evil.example/x> a <http://evil.example/Y> .\n"""',
    "\\\" \\u0022 \\\\",
    "<http://evil.example/iri>",
    "x@en ^^<http://www.w3.org/2001/XMLSchema#integer>",
    "{BASE_URI}bajas",
]


@pytest.mark.parametrize("text", HOSTILE)
def test_titulo_y_publicador_hostiles_quedan_como_literales(
    stack: Stack, editor: Account, text: str
) -> None:
    base = _base(stack)
    slug = _slug("inj")
    line = text.replace("\n", " ")  # título y publicador son de una línea (422 con salto)
    body = {"slug": slug, "title": line, "description": text, "publisher_name": line}
    created = _api(stack, "POST", "/catalogs", editor.token, body)
    assert created.status == 201, created.text
    assert _json(created)["title"] == line and _json(created)["description"] == text
    graph = f"{base}catalogo/{slug}"
    triples = _fuseki(stack, f"SELECT ?p ?o WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}")["results"]["bindings"]
    # Tipo, título, descripción, publicador y los tres del nodo del publicador. Nada más.
    predicates = sorted(t["p"]["value"].rsplit("/", 1)[-1].rsplit("#", 1)[-1] for t in triples)
    assert predicates == ["description", "name", "publisher", "title", "type", "type", "type"], predicates
    assert all(t["o"]["type"] != "uri" or t["p"]["value"].endswith(("type", "#type")) for t in triples)
    assert not _fuseki(stack, "ASK { <http://evil.example/x> ?p ?o }")["boolean"]
    # Y en un dataset.
    dslug = _slug("dinj")
    dataset = _dataset(stack, editor.token, slug, dslug, line)
    assert dataset.status == 201, dataset.text
    assert not _fuseki(stack, "ASK { <http://evil.example/x> ?p ?o }")["boolean"]
    assert _api(stack, "PATCH", f"/datasets/{dslug}", editor.token, {"title": line, "publisher_name": line}).status == 200


@pytest.mark.parametrize(
    "slug",
    ["a> . <http://evil/x", "../x", "A", "a_b", "a b", "é", "a" * 201, "", "-a", "a/b", "a%2Fb", "a\nb",
     "a\x00b"],
)
def test_slugs_maliciosos_se_rechazan(stack: Stack, editor: Account, slug: str) -> None:
    before = _fuseki(stack, "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }")
    assert _catalog(stack, editor.token, slug).status == 422
    assert _api(stack, "POST", "/catalogs/x/datasets", editor.token, {"slug": slug, "title": "t", "description": "d"}).status in (404, 422)
    assert _fuseki(stack, "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }") == before


@pytest.mark.parametrize(
    "path",
    ["/catalogs/a%3E%20.%20%3Cx", "/catalogs/..%2f..%2fx", "/catalogs/A", "/datasets/%00",
     "/datasets?catalog=a%22%20%7D%20UNION%20%7B", "/datasets?catalog=A", "/datasets/..%2fx"],
)
def test_rutas_y_parametros_maliciosos_no_llegan_al_triplestore(stack: Stack, path: str) -> None:
    response = http("GET", f"{stack.api}{path}")
    assert response.status in (404, 422), (path, response.status, response.text[:200])
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "body",
    [{"slug": "x-ctl", "title": "a\nb", "description": "d", "publisher_name": "p"},
     {"slug": "x-ctl", "title": "a\x00b", "description": "d", "publisher_name": "p"},
     {"slug": "x-ctl", "title": "t", "description": "d\x07", "publisher_name": "p"},
     {"slug": "x-ctl", "title": "t" * 100_000, "description": "d", "publisher_name": "p"},
     {"slug": "x-ctl", "title": "t", "description": "d", "publisher_name": "p", "extra": "x"},
     {"slug": "x-ctl", "title": None, "description": "d", "publisher_name": "p"},
     {"slug": "x-ctl", "title": ["t"], "description": "d", "publisher_name": "p"}],
)
def test_cuerpos_no_validos_dan_422_sin_reflejar_el_valor(
    stack: Stack, editor: Account, body: dict
) -> None:
    response = _api(stack, "POST", "/catalogs", editor.token, body)
    assert response.status == 422, response.text[:200]
    assert '"input"' not in response.text and '"ctx"' not in response.text
    assert http("GET", f"{stack.api}/catalogs/x-ctl").status == 404


def test_iri_maliciosa_en_catalog_del_patch_y_del_query(stack: Stack, editor: Account, cat: str) -> None:
    d = _slug("iri")
    assert _dataset(stack, editor.token, cat, d).status == 201
    for bad in ("http://evil.example/catalogo/x", "a> . <b", "../cat", f"{cat}/../x", "A"):
        assert _api(stack, "PATCH", f"/datasets/{d}", editor.token, {"catalog": bad}).status == 422, bad
        assert _publish(stack, _series_ttl(d, None, {"csv": "PUBLIC"}), editor.token, f"?catalog={urllib.parse.quote(bad)}").status == 422, bad
    # Un RDF que cuelga de un catálogo ajeno con propiedades de más: 422, sin escribir.
    ttl = _series_ttl(d, cat, {"csv": "PUBLIC"}) + f'<catalogo/{cat}> <http://purl.org/dc/terms/title> "Secuestrado"@es .\n'
    assert _publish(stack, ttl, editor.token).status == 422
    assert _json(http("GET", f"{stack.api}/catalogs/{cat}"))["title"] != "Secuestrado"
    ttl = _series_ttl(d, cat, {"csv": "PUBLIC"}).replace("@prefix dct:", "<http://evil.example/catalogo/x> dcat:dataset <dataset/" + d + "> .\n@prefix dct:", 1)
    ttl = "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n" + ttl
    assert _publish(stack, ttl, editor.token).status == 422


# --- 8. Ficheros: se eliminan, también en datasets de defensa ---------------------------


def _files_on_disk(stack: Stack, slug: str) -> list[str]:
    result = stack.compose("exec", "-T", "backend", "sh", "-c", f"find /data/distributions/{slug} -type f 2>/dev/null")
    return [line for line in result.stdout.splitlines() if line]


def _file_rows(stack: Stack, slug: str) -> list[str]:
    return stack.psql(f"select storage_key from distribution_files where storage_key like '{slug}/%'")


def test_la_baja_elimina_los_ficheros_y_sus_filas(stack: Stack, editor: Account, cat: str) -> None:
    slug, sibling = _slug("fich"), _slug("fich") + "-2"
    for s in (slug, sibling):
        assert _publish(stack, _series_ttl(s, cat, {"abierta": "PUBLIC", "restringida": "RESTRICTED"}), editor.token).status == 201
        for dist in ("abierta", "restringida"):
            assert _put_file(stack, s, dist, f"contenido {s} {dist}".encode(), editor.token).status == 201
    assert len(_files_on_disk(stack, slug)) == 2 and len(_file_rows(stack, slug)) == 2
    assert _api(stack, "DELETE", f"/datasets/{slug}", editor.token).status == 204
    assert _files_on_disk(stack, slug) == [] and _file_rows(stack, slug) == []
    ls = stack.compose("exec", "-T", "backend", "ls", "/data/distributions")
    assert slug not in ls.stdout.split()  # ni siquiera la carpeta
    # Un slug que empieza igual no pierde nada (el prefijo es «slug/»).
    assert len(_files_on_disk(stack, sibling)) == 2 and len(_file_rows(stack, sibling)) == 2
    assert http("GET", f"{stack.api}/dataset/{sibling}/1.0.0/abierta/fichero").status == 200
    event = _audit(stack, "dataset_withdrawn")[-1]
    assert event["details"]["slug"] == slug
    assert sorted(event["details"]["files_deleted"]) == [f"{slug}/1.0.0/abierta", f"{slug}/1.0.0/restringida"]
    assert event["details"]["files_not_deleted"] == []


def test_dar_de_baja_un_dataset_de_defensa_no_deja_ficheros(
    stack: Stack, editor: Account, cat: str
) -> None:
    """NON_PUBLIC no admite fichero (409 non_public) y la baja no deja nada en disco ni en
    ``distribution_files``, ni siquiera en una versión que mezcla accesos."""
    slug = _slug("def")
    ttl = _series_ttl(slug, cat, {"cerrada": "NON_PUBLIC", "restringida": "RESTRICTED"})
    assert _publish(stack, ttl, editor.token).status == 201
    response = _put_file(stack, slug, "cerrada", b"no debe guardarse", editor.token)
    assert response.status == 409 and "non_public" in response.text
    assert _files_on_disk(stack, slug) == []
    assert _put_file(stack, slug, "restringida", b"restringido", editor.token).status == 201
    assert _api(stack, "DELETE", f"/datasets/{slug}", editor.token).status == 204
    assert _files_on_disk(stack, slug) == [] and _file_rows(stack, slug) == []
    for dist in ("cerrada", "restringida"):
        assert http("GET", f"{stack.api}/dataset/{slug}/1.0.0/{dist}/fichero").status == 410
    # La distribución de defensa solo publica metadatos: tras la baja, tampoco están.
    assert not _fuseki(stack, f"ASK {{ GRAPH ?g {{ <{_base(stack)}dataset/{slug}/1.0.0/cerrada> ?p ?o }} }}")["boolean"]


@pytest.mark.xfail(
    strict=True,
    reason="QA-49-02: la baja solo borra las claves de distribution_files; un fichero huérfano "
    "(sin fila) queda en disco",
)
def test_un_fichero_huerfano_en_disco_tambien_se_elimina(
    stack: Stack, editor: Account, cat: str
) -> None:
    """Un fichero sin fila en ``distribution_files`` (escritura interrumpida) de un dataset
    dado de baja no puede quedarse en disco."""
    slug = _slug("huer")
    assert _publish(stack, _series_ttl(slug, cat, {"csv": "RESTRICTED"}), editor.token).status == 201
    made = stack.compose("exec", "-T", "backend", "sh", "-c",
                         f"mkdir -p /data/distributions/{slug}/1.0.0 && echo huerfano > /data/distributions/{slug}/1.0.0/csv")
    assert made.returncode == 0, made.stderr
    assert _api(stack, "DELETE", f"/datasets/{slug}", editor.token).status == 204
    assert _files_on_disk(stack, slug) == []


# --- 9. Auditoría -----------------------------------------------------------------------


def test_todo_queda_en_la_auditoria(stack: Stack, admin: Account, editor: Account) -> None:
    base = _base(stack)
    c, d = _slug("aud"), _slug("aud")
    created = _catalog(stack, editor.token, c, "Título auditable")
    assert created.status == 201
    assert _dataset(stack, admin.token, c, d, "Título auditable").status == 201
    assert _api(stack, "PATCH", f"/catalogs/{c}", editor.token, {"title": "Otro"}).status == 200
    assert _api(stack, "PATCH", f"/datasets/{d}", admin.token, {"title": "Otro"}).status == 200
    assert _api(stack, "DELETE", f"/datasets/{d}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/catalogs/{c}", admin.token).status == 204
    expected = {
        "catalog_created": (f"{base}catalogo/{c}", "catalog", editor),
        "catalog_updated": (f"{base}catalogo/{c}", "catalog", editor),
        "catalog_withdrawn": (f"{base}catalogo/{c}", "catalog", admin),
        "dataset_created": (f"{base}dataset/{d}", "series", admin),
        "dataset_updated": (f"{base}dataset/{d}", "series", admin),
        "dataset_withdrawn": (f"{base}dataset/{d}", "series", editor),
    }
    for action, (uri, key, actor) in expected.items():
        events = [e for e in _audit(stack, action) if e["details"].get(key) == uri]
        assert len(events) == 1, (action, events)
        assert events[0]["actor_username"] == actor.username
        assert events[0]["details"]["via"] == "api"
    dump = "\n".join(stack.psql("select row_to_json(a) from audit_events a order by a.id"))
    assert "Título auditable" not in dump  # los títulos no van a la auditoría
    for name, secret in stack.sensitive.items():
        assert secret not in dump, name


def test_los_409_y_422_no_escriben_en_la_auditoria(stack: Stack, editor: Account, cat: str) -> None:
    def total() -> int:
        return int(stack.psql("select count(*) from audit_events where action like 'catalog_%' or action like 'dataset_%'")[0])

    before = total()
    assert _catalog(stack, editor.token, cat).status == 409
    assert _catalog(stack, editor.token, "Mal Slug").status == 422
    assert _api(stack, "DELETE", f"/catalogs/{_slug('no')}", editor.token).status == 404
    assert total() == before


# --- 10. Concurrencia -------------------------------------------------------------------


def _parallel(calls: list) -> list:
    results: list = [None] * len(calls)

    def run(i: int, call) -> None:
        results[i] = call()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


@pytest.mark.xfail(
    strict=True,
    reason="QA-49-01: add_to_root lee y reescribe el grafo del raíz entero (pérdida de "
    "actualizaciones con altas simultáneas)",
)
def test_altas_simultaneas_de_catalogos_no_pierden_enlaces_del_raiz(
    stack: Stack, editor: Account
) -> None:
    """``dcat:catalog`` del raíz se escribe leyendo y reescribiendo el grafo entero: con altas
    simultáneas no puede perderse ningún enlace."""
    base = _base(stack)
    cats = [_slug("par") for _ in range(8)]
    statuses = _parallel([lambda s=s: _catalog(stack, editor.token, s).status for s in cats])
    assert statuses == [201] * 8, statuses
    linked = {
        r["c"]["value"]
        for r in _fuseki(
            stack,
            f"SELECT ?c WHERE {{ GRAPH <{base}catalogo> {{ <{base}catalogo> <http://www.w3.org/ns/dcat#catalog> ?c }} }}",
        )["results"]["bindings"]
    }
    missing = [s for s in cats if f"{base}catalogo/{s}" not in linked]
    assert missing == [], f"enlaces del raíz perdidos: {missing}"


@pytest.mark.xfail(
    strict=True,
    reason="QA-49-01: add_tombstone lee y reescribe el grafo bajas entero (pérdida de "
    "lápidas con bajas simultáneas)",
)
def test_bajas_simultaneas_no_pierden_lapidas(stack: Stack, editor: Account) -> None:
    """Las lápidas se añaden leyendo y reescribiendo el grafo ``bajas`` entero: con bajas
    simultáneas ninguna puede perderse (el slug quedaría reutilizable y el 410 sería 404)."""
    cats = [_slug("bpar") for _ in range(8)]
    for s in cats:
        assert _catalog(stack, editor.token, s).status == 201
    statuses = _parallel([lambda s=s: _api(stack, "DELETE", f"/catalogs/{s}", editor.token).status for s in cats])
    assert statuses == [204] * 8, statuses
    lost = [s for s in cats if http("GET", f"{stack.api}/catalogs/{s}").status != 410]
    assert lost == [], f"lápidas perdidas: {lost}"


# --- 11. load-semantic conserva lo hecho desde la aplicación -----------------------------


def test_load_semantic_conserva_catalogos_datasets_y_traslados(
    stack: Stack, editor: Account, cat: str
) -> None:
    base = _base(stack)
    slug = "hallazgos-auditorias-intrusion"
    d = _slug("keep")
    assert _dataset(stack, editor.token, cat, d).status == 201
    assert _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"catalog": cat}).status == 200
    code, output = _load_semantic(stack)
    assert code == 0, output
    # Lo creado desde la aplicación sigue ahí, en el raíz y en su catálogo.
    assert http("GET", f"{stack.api}/datasets/{d}").status == 200
    assert _ask_graph(stack, f"{base}catalogo", f"<{base}catalogo> <http://www.w3.org/ns/dcat#catalog> <{base}catalogo/{cat}>")
    members = {x["slug"] for x in _json(http("GET", f"{stack.api}/catalogs/{cat}"))["datasets"]}  # type: ignore[index]
    assert {d, slug} <= members  # y el traslado de un sintético no se deshace
    assert slug not in {x["slug"] for x in _json(http("GET", f"{stack.api}/catalogs/sintetico"))["datasets"]}  # type: ignore[index]
    # Se devuelve a su catálogo y la recarga es idempotente.
    assert _api(stack, "PATCH", f"/datasets/{slug}", editor.token, {"catalog": "sintetico"}).status == 200
    code, output = _load_semantic(stack)
    assert code == 0, output
    lines = [line for line in output.splitlines() if " -> <" in line]
    assert lines and all("sin cambios" in line for line in lines), output


def test_load_semantic_no_resucita_lo_dado_de_baja(stack: Stack, editor: Account) -> None:
    """Último de G5: da de baja un dataset sintético (con sus ficheros) y recarga. Nada de
    lo que se ejecute después puede contar con ``ejemplos-adversarios-vision``."""
    slug = "ejemplos-adversarios-vision"
    base = _base(stack)
    assert _files_on_disk(stack, slug)
    assert _api(stack, "DELETE", f"/datasets/{slug}", editor.token).status == 204
    assert _files_on_disk(stack, slug) == []
    code, output = _load_semantic(stack)
    assert code == 0, output
    assert "se omite" in output and slug in output
    assert http("GET", f"{stack.api}/datasets/{slug}").status == 410
    assert _files_on_disk(stack, slug) == [] and _file_rows(stack, slug) == []
    assert not _fuseki(stack, f"ASK {{ GRAPH <{base}dataset/{slug}> {{ ?s ?p ?o }} }}")["boolean"]
    assert slug not in {x["slug"] for x in _json(http("GET", f"{stack.api}/catalogs/sintetico"))["datasets"]}  # type: ignore[index]
    assert _publish(stack, _series_ttl(slug, "sintetico", {"csv": "PUBLIC"}), editor.token).status == 409
