"""Puerta G2 · «primer dataset publicado», de extremo a extremo sobre Docker Compose.

Recorre el criterio de la puerta con el Compose real: ``load-semantic`` carga el
vocabulario mínimo, el catálogo y las tres series sintéticas; el catálogo las lista y
filtra; la ficha muestra la versión actual y las antiguas; el RDF sale en Turtle y en
JSON-LD; las URIs persistentes redirigen (303) a la ficha del frontend; un editor publica
una serie por la API y aparece en el catálogo; la ingesta que no cumple las formas SHACL se
rechaza con 422, y todo lo sintético lleva la marca.

Las pruebas comparten el entorno de ``conftest.py`` (el mismo que G1) y se ejecutan en el
orden del fichero. Crean sus propias cuentas: no dependen de las de G1, que acaban con el
rol cambiado o dadas de baja. Cómo lanzarlas: ``tests/e2e/README.md``.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import urllib.parse
from http.client import HTTPConnection

import pytest
from conftest import (
    REPO_ROOT,
    Account,
    Response,
    Stack,
    create_account,
    fuseki_logged,
    fuseki_probe_url,
    http,
    wait_for_http,
)

SYNTHETIC_DIR = REPO_ROOT / "semantic" / "data" / "sintetico"
INVALID_DIR = REPO_ROOT / "semantic" / "examples" / "invalid"

# Slug, versión actual, dominio y título de las tres series sintéticas de G2. El título
# se comprueba además contra el propio fichero de semantic/data/sintetico/.
SYNTHETIC = {
    "ejemplos-adversarios-vision": ("0.9.0", "ia"),
    "hallazgos-auditorias-intrusion": ("1.3.0", "it"),
    "modbus-tcp-testbed": ("2.1.0", "ot"),
}
MODBUS_VERSIONS = ["2.1.0", "2.0.0", "1.0.0"]
PUBLIC = "http://publications.europa.eu/resource/authority/access-right/PUBLIC"
TURTLE = {"Content-Type": "text/turtle"}
JSONLD = {"Content-Type": "application/ld+json"}
INGEST_MAX_BYTES = 10 * 1024 * 1024  # valor por defecto del backend (no está en .env.example)


# --- Utilidades ------------------------------------------------------------------------


def _base_uri(stack: Stack) -> str:
    return stack.env["BASE_URI"]


def _sparql(stack: Stack, query: str) -> list[dict]:
    """Consulta anónima a Fuseki (la lectura es pública; ver G1)."""
    response = http(
        "POST",
        f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/sparql",
        form={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    return response.json()["results"]["bindings"]  # type: ignore[index]


def _graphs(stack: Stack) -> dict[str, int]:
    """Grafos con nombre de Fuseki y su número de triples."""
    rows = _sparql(stack, "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g")
    return {row["g"]["value"]: int(row["n"]["value"]) for row in rows}


def _load_semantic(stack: Stack) -> tuple[int, str]:
    result = stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=300
    )
    return result.returncode, result.stdout + result.stderr


def _published_events(stack: Stack) -> list[dict]:
    return [
        json.loads(line)
        for line in stack.psql(
            "select row_to_json(a) from audit_events a "
            "where a.action = 'dataset_published' order by a.id"
        )
    ]


def _datasets(stack: Stack, **params: str) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    response = http("GET", f"{stack.api}/datasets{query}")
    assert response.status == 200, response.text
    return response.json()  # type: ignore[return-value]


def _slugs(stack: Stack, **params: str) -> list[str]:
    return sorted(item["slug"] for item in _datasets(stack, **params)["items"])


def _publish(
    stack: Stack, body: str | bytes, token: str | None, headers: dict[str, str] = TURTLE
) -> Response:
    raw = body.encode() if isinstance(body, str) else body
    return http("POST", f"{stack.api}/datasets", raw_body=raw, headers=headers, token=token)


def _series_ttl(slug: str, title: str, *, version: str = "1.0.0", extra: str = "") -> str:
    """Serie mínima válida de prueba, marcada como sintética y con un tema del dominio OT.
    Lleva su triple de pertenencia al catálogo ``e2e-pruebas`` (decisión 49), que crea el
    fixture ``e2e_catalog`` de ``conftest.py``.

    Los textos son de relleno de la prueba, no datos del prototipo ni reales.
    """
    return f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct:  <http://purl.org/dc/terms/> .
<catalogo/e2e-pruebas> dcat:dataset <dataset/{slug}> .
<dataset/{slug}> a dcat:DatasetSeries ;
    dct:type <vocab/tipo-dataset/sintetico> ;
    dct:title "{title}"@es ;
    dct:description "Serie creada por la prueba de extremo a extremo de G2."@es ;
    dcat:last <dataset/{slug}/{version}> .
<dataset/{slug}/{version}> a dcat:Dataset ;
    dct:type <vocab/tipo-dataset/sintetico> ;
    dct:title "{title}"@es ;
    dct:description "Serie creada por la prueba de extremo a extremo de G2."@es ;
    dcat:version "{version}" ;
    dcat:inSeries <dataset/{slug}> ;
    dct:accessRights <{PUBLIC}> ;
    dcat:theme <vocab/ot/modbus-tcp> ;
    dcat:distribution <dataset/{slug}/{version}/csv> .
<dataset/{slug}/{version}/csv> a dcat:Distribution ;
    dct:title "CSV"@es ;
    dcat:mediaType <http://www.iana.org/assignments/media-types/text/csv> ;
    dcat:accessURL <dataset/{slug}/{version}/csv> .
{extra}
"""


def _file_title(slug: str) -> str:
    text = (SYNTHETIC_DIR / f"{slug}.ttl").read_text(encoding="utf-8")
    match = re.search(r'^\s*dct:title "([^"]+)"@es', text, flags=re.MULTILINE)
    assert match, slug
    return match.group(1)


# --- Fixtures --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def g2_editor(stack: Stack, admin: Account, e2e_catalog: str) -> Account:
    return create_account(stack, admin, "editor")


@pytest.fixture(scope="module")
def g2_member(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "miembro")


@pytest.fixture(scope="module")
def loaded(stack: Stack) -> str:
    """Ejecuta ``load-semantic`` una vez y devuelve su salida."""
    code, output = _load_semantic(stack)
    assert code == 0, f"load-semantic falló:\n{output}"
    return output


@pytest.fixture(scope="module")
def published(stack: Stack, loaded: str, g2_editor: Account) -> dict:
    """Publica por la API, como editor, una serie nueva. Devuelve slug, título y respuesta."""
    slug = f"e2e-{secrets.token_hex(4)}"
    title = f"Serie de prueba {slug}"
    response = _publish(stack, _series_ttl(slug, title), g2_editor.token)
    assert response.status == 201, response.text
    return {"slug": slug, "title": title, "body": response.json()}


# --- 1. Entorno de la fase 2 -----------------------------------------------------------


def test_los_cuatro_servicios_estan_sanos_incluido_el_frontend(stack: Stack) -> None:
    result = stack.compose("ps", "--all", "--format", "json")
    assert result.returncode == 0, result.stderr
    text = result.stdout.strip()
    rows = json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines()]
    health = {row["Service"]: row["Health"] for row in rows}
    # El frontend declara healthcheck desde la fase 2 y F-UJI (fase 4) también: todos healthy.
    expected = ("postgres", "fuseki", "fuji", "backend", "frontend")
    assert health == {name: "healthy" for name in expected}


def test_el_backend_recibe_semantic_y_las_credenciales_de_fuseki(stack: Stack) -> None:
    """Contrato infra-backend de la fase 2: variables y montaje de ``./semantic``."""
    result = stack.compose("config", "--format", "json")
    assert result.returncode == 0, result.stderr
    backend = json.loads(result.stdout)["services"]["backend"]
    environment = backend["environment"]
    assert environment["SEMANTIC_DIR"] == "/semantic"
    # Fase 4 (decisión 32): el backend escribe con su propio usuario, no con `admin`.
    assert environment["FUSEKI_USER"] == stack.env["FUSEKI_USER"] == "backend"
    assert environment["FUSEKI_PASSWORD"] == stack.env["FUSEKI_BACKEND_PASSWORD"]
    assert environment["FUSEKI_PASSWORD"] != stack.env["FUSEKI_ADMIN_PASSWORD"]
    assert environment["FRONTEND_BASE_URL"] == stack.env["FRONTEND_BASE_URL"]
    mounts = [v for v in backend["volumes"] if v.get("target") == "/semantic"]
    assert len(mounts) == 1
    assert mounts[0]["source"] == str(REPO_ROOT / "semantic")
    assert mounts[0].get("read_only") is True

    listing = stack.compose("exec", "-T", "backend", "ls", "/semantic/data/sintetico")
    assert listing.returncode == 0, listing.stderr
    # Los tres .ttl y, desde la fase 4, la carpeta `ficheros` de las distribuciones sintéticas.
    assert sorted(listing.stdout.split()) == sorted(
        [f"{slug}.ttl" for slug in SYNTHETIC] + ["ficheros"]
    )
    # Solo lectura: el backend no puede modificar las formas ni los datos versionados.
    write = stack.compose("exec", "-T", "backend", "touch", "/semantic/shapes/qa-e2e.ttl")
    assert write.returncode != 0
    assert not (REPO_ROOT / "semantic" / "shapes" / "qa-e2e.ttl").exists()


def test_el_catalogo_esta_vacio_antes_de_cargar(stack: Stack) -> None:
    if _graphs(stack):
        pytest.skip("el triplestore ya tiene datos (prueba lanzada suelta tras la carga)")
    assert _datasets(stack) == {"items": [], "total": 0, "page": 1, "page_size": 20}
    assert http("GET", f"{stack.api}/datasets/modbus-tcp-testbed").status == 404
    assert http("GET", f"{stack.api}/dataset/modbus-tcp-testbed").status == 404


# --- 2. load-semantic ------------------------------------------------------------------


def test_load_semantic_carga_las_cinco_piezas(stack: Stack, loaded: str) -> None:
    base = _base_uri(stack)
    # Desde la fase 3, los dos esquemas auxiliares de vocab-minimo.ttl van cada uno en el
    # grafo de su URI (antes, juntos en {BASE_URI}vocab/).
    expected = {
        "vocab-minimo.ttl (dominio)": f"{base}vocab/dominio",
        "vocab-minimo.ttl (tipo-dataset)": f"{base}vocab/tipo-dataset",
        "catalogo.ttl": f"{base}catalogo",
        "catalogos/sintetico.ttl": f"{base}catalogo/sintetico",  # decisión 49
        **{f"{slug}.ttl": f"{base}dataset/{slug}" for slug in SYNTHETIC},
    }
    for name, graph in expected.items():
        assert f"{name} -> <{graph}>" in loaded, loaded
    graphs = _graphs(stack)
    assert set(expected.values()) <= set(graphs)
    assert all(graphs[graph] > 0 for graph in expected.values())
    # Todo va a grafos con nombre: el grafo por defecto de Fuseki es la unión de ellos
    # (tdb2:unionDefaultGraph), así que no hay triples fuera de los grafos listados.
    default = _sparql(stack, "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
    assert int(default[0]["n"]["value"]) <= sum(graphs.values())
    for secret in stack.sensitive.values():
        assert secret not in loaded


def test_load_semantic_es_idempotente(stack: Stack, loaded: str) -> None:
    before = _graphs(stack)
    code, output = _load_semantic(stack)
    assert code == 0, output
    lines = [line for line in output.splitlines() if " -> <" in line]
    # Las piezas de la fase 2 (el vocabulario mínimo son ahora dos esquemas, cada uno en
    # su grafo). Desde la fase 3 hay más: el recuento exacto está en la prueba de G3.
    assert len(lines) >= 6, output
    assert all("sin cambios" in line for line in lines), output
    assert _graphs(stack) == before


def test_load_semantic_queda_en_la_auditoria(stack: Stack, loaded: str) -> None:
    base = _base_uri(stack)
    events = [e for e in _published_events(stack) if e["details"]["via"] == "cli"]
    assert {e["details"]["series"] for e in events} == {f"{base}dataset/{s}" for s in SYNTHETIC}
    for event in events:
        assert event["actor_id"] is None
        assert event["actor_username"] == "cli"
        assert event["details"]["graph"] == event["details"]["series"]
    first = {e["details"]["slug"]: e for e in reversed(events)}  # el más antiguo de cada serie
    assert all(e["details"]["created"] and e["details"]["changed"] for e in first.values())
    assert first["modbus-tcp-testbed"]["details"]["versions"] == sorted(MODBUS_VERSIONS)


# --- 3. Catálogo -----------------------------------------------------------------------


def test_el_catalogo_lista_los_tres_datasets_sinteticos(stack: Stack, loaded: str) -> None:
    page = _datasets(stack)
    assert page["total"] == 3
    items = {item["slug"]: item for item in page["items"]}
    assert set(items) == set(SYNTHETIC)
    base = _base_uri(stack)
    for slug, (version, domain) in SYNTHETIC.items():
        item = items[slug]
        assert item["uri"] == f"{base}dataset/{slug}"
        assert item["title"] == _file_title(slug)
        assert item["description"]
        assert item["current_version"] == version
        assert item["domain"]["slug"] == domain
        assert item["domain"]["label"], slug
        assert item["themes"] and all(theme["label"] for theme in item["themes"])
        assert item["formats"], slug
        assert item["access_rights"]["code"] == "RESTRICTED"
        assert item["synthetic"] is True, f"{slug} no lleva la marca de sintético"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"domain": "ot"}, ["modbus-tcp-testbed"]),
        ({"domain": "it"}, ["hallazgos-auditorias-intrusion"]),
        ({"domain": "ia"}, ["ejemplos-adversarios-vision"]),
        ({"domain": "pqc"}, []),
        ({"q": "cwe"}, ["hallazgos-auditorias-intrusion"]),
        ({"q": "MODBUS"}, ["modbus-tcp-testbed"]),
        ({"q": "trafico"}, ["modbus-tcp-testbed"]),  # sin acento encuentra «Tráfico»
        ({"q": "adversarios"}, ["ejemplos-adversarios-vision"]),
        ({"q": "modbus", "domain": "ot"}, ["modbus-tcp-testbed"]),
        ({"q": "modbus", "domain": "it"}, []),
        ({"q": "no-existe-este-texto"}, []),
        ({"q": '" } UNION { GRAPH ?g { ?s ?p ?o } } #'}, []),
    ],
)
def test_los_filtros_del_catalogo(
    stack: Stack, loaded: str, params: dict[str, str], expected: list[str]
) -> None:
    found = [slug for slug in _slugs(stack, **params) if slug in SYNTHETIC]
    assert found == expected


def test_el_catalogo_valida_sus_parametros(stack: Stack, loaded: str) -> None:
    for query in (
        "domain=otro",
        "domain=OT",
        "page=0",
        "page_size=101",
        f"q={'a' * 201}",
    ):
        assert http("GET", f"{stack.api}/datasets?{query}").status == 422, query


def test_la_paginacion_recorre_todo_el_catalogo(stack: Stack, loaded: str) -> None:
    total = _datasets(stack)["total"]
    seen: list[str] = []
    for page in range(1, total + 1):
        body = _datasets(stack, page=str(page), page_size="1")
        assert body["total"] == total
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["slug"])
    assert len(set(seen)) == total
    assert _datasets(stack, page=str(total + 1), page_size="1")["items"] == []


def test_el_navegador_puede_leer_el_catalogo_desde_el_frontend(stack: Stack, loaded: str) -> None:
    """CORS: el origen del frontend puede leer el catálogo; otro origen, no."""
    allowed = http("GET", f"{stack.api}/datasets", headers={"Origin": stack.frontend_origin})
    assert allowed.headers.get("access-control-allow-origin") == stack.frontend_origin
    other = http("GET", f"{stack.api}/datasets", headers={"Origin": "http://127.0.0.1:1"})
    assert "access-control-allow-origin" not in other.headers


# --- 4. Ficha y versiones --------------------------------------------------------------


def test_la_ficha_muestra_la_version_actual_y_el_historial(stack: Stack, loaded: str) -> None:
    base = _base_uri(stack)
    response = http("GET", f"{stack.api}/datasets/modbus-tcp-testbed")
    assert response.status == 200, response.text
    detail = response.json()
    assert detail["slug"] == "modbus-tcp-testbed"
    assert detail["uri"] == f"{base}dataset/modbus-tcp-testbed"
    assert detail["title"] == _file_title("modbus-tcp-testbed")
    assert detail["current_version"] == "2.1.0"
    assert detail["synthetic"] is True
    assert detail["domain"]["slug"] == "ot"
    assert [v["version"] for v in detail["versions"]] == MODBUS_VERSIONS
    assert [v["current"] for v in detail["versions"]] == [True, False, False]

    version = detail["version"]
    assert version["version"] == "2.1.0"
    assert version["uri"] == f"{base}dataset/modbus-tcp-testbed/2.1.0"
    assert version["in_series"] == detail["uri"]
    assert version["synthetic"] is True
    assert version["previous_version"]["version"] == "2.0.0"
    assert version["metadata"]["access_rights"]["code"] == "RESTRICTED"
    assert len(version["distributions"]) == 3
    for distribution in version["distributions"]:
        # dcat:accessURL es la URI de la propia distribución (decisión 17).
        assert distribution["uri"].startswith(version["uri"] + "/")
        assert distribution["access_url"] == distribution["uri"]
    # Placeholders del prototipo sin valor real: no se inventan.
    assert version["metadata"]["license"] is None
    assert version["metadata"]["contact_point"] is None
    assert version["metadata"]["issued"] is None
    assert not re.search(r"\[[A-ZÁÉÍÓÚÑ]+\]", json.dumps(detail, ensure_ascii=False))


def test_las_versiones_antiguas_tienen_ficha(stack: Stack, loaded: str) -> None:
    for slug in SYNTHETIC:
        detail = http("GET", f"{stack.api}/datasets/{slug}").json()
        assert detail["versions"], slug
        for entry in detail["versions"]:
            if not entry["described"]:
                continue
            url = f"{stack.api}/datasets/{slug}?version={entry['version']}"
            response = http("GET", url)
            assert response.status == 200, url
            body = response.json()
            assert body["version"]["version"] == entry["version"]
            assert body["version"]["uri"] == entry["uri"]
            # La serie sigue apuntando a la versión actual aunque se pida una antigua.
            assert body["current_version"] == detail["current_version"]
            assert body["version"]["synthetic"] is True, url
    old = http("GET", f"{stack.api}/datasets/modbus-tcp-testbed?version=1.0.0").json()
    assert old["version"]["previous_version"] is None
    assert len(old["version"]["distributions"]) == 2


def test_fichas_y_versiones_que_no_existen(stack: Stack, loaded: str) -> None:
    api = stack.api
    assert http("GET", f"{api}/datasets/no-existe").status == 404
    assert http("GET", f"{api}/datasets/modbus-tcp-testbed?version=9.9.9").status == 404
    assert http("GET", f"{api}/datasets/modbus-tcp-testbed?version=2.1").status == 422
    assert http("GET", f"{api}/datasets/Modbus_TCP").status == 422
    assert http("GET", f"{api}/datasets/modbus-tcp-testbed%0A").status == 422
    # El catálogo y el vocabulario no son series: no se pueden pedir por slug.
    for slug in ("catalogo", "vocab", "ot"):
        assert http("GET", f"{api}/datasets/{slug}").status == 404
        assert http("GET", f"{api}/dataset/{slug}").status == 404


# --- 5. RDF ----------------------------------------------------------------------------


def test_rdf_en_turtle_y_en_json_ld(stack: Stack, loaded: str) -> None:
    base = _base_uri(stack)
    url = f"{stack.api}/datasets/modbus-tcp-testbed/rdf"
    version_uri = f"{base}dataset/modbus-tcp-testbed/2.1.0"

    turtle = http("GET", f"{url}?format=turtle")
    assert turtle.status == 200
    assert turtle.headers["content-type"].startswith("text/turtle")
    assert "dcat:Dataset" in turtle.text
    assert "2.1.0" in turtle.text

    jsonld = http("GET", f"{url}?format=jsonld")
    assert jsonld.status == 200
    assert jsonld.headers["content-type"].startswith("application/ld+json")
    document = json.loads(jsonld.text)
    assert "@context" in document
    assert version_uri in jsonld.text or "itotd:modbus-tcp-testbed/2.1.0" in jsonld.text

    # Sin ?format decide la cabecera Accept.
    negotiated = {
        "text/turtle": "text/turtle",
        "application/ld+json": "application/ld+json",
        "application/ld+json;q=0.9, text/turtle;q=0.1": "application/ld+json",
        "*/*": "text/turtle",
    }
    for accept, media in negotiated.items():
        response = http("GET", url, headers={"Accept": accept})
        assert response.status == 200, accept
        assert response.headers["content-type"].startswith(media), accept
        assert "Accept" in response.headers.get("vary", "")
    assert http("GET", url, headers={"Accept": "text/csv"}).status == 406
    assert http("GET", f"{url}?format=rdfxml").status == 422
    assert http("GET", f"{stack.api}/datasets/no-existe/rdf").status == 404


def test_rdf_de_una_version_antigua(stack: Stack, loaded: str) -> None:
    url = f"{stack.api}/datasets/modbus-tcp-testbed/rdf?format=turtle&version=1.0.0"
    old = http("GET", url)
    assert old.status == 200
    assert '"1.0.0"' in old.text
    assert '"2.1.0"' not in old.text
    assert http("GET", url.replace("1.0.0", "9.9.9")).status == 404


def test_todo_lo_sintetico_lleva_la_marca(stack: Stack, loaded: str) -> None:
    """La marca ``dct:type <{BASE_URI}vocab/tipo-dataset/sintetico>`` está en cada serie y
    en cada versión sintética, en el triplestore, en la API y en el RDF que se sirve."""
    base = _base_uri(stack)
    marker = f"{base}vocab/tipo-dataset/sintetico"

    # En el triplestore: ninguna serie ni versión de las tres series carece de la marca.
    for slug in SYNTHETIC:
        graph = f"{base}dataset/{slug}"
        unmarked = _sparql(
            stack,
            "PREFIX dcat: <http://www.w3.org/ns/dcat#> PREFIX dct: <http://purl.org/dc/terms/> "
            f"SELECT ?r WHERE {{ GRAPH <{graph}> {{ "
            "{ ?r a dcat:DatasetSeries } UNION { ?r a dcat:Dataset } "
            f"FILTER NOT EXISTS {{ ?r dct:type <{marker}> }} }} }}",
        )
        assert unmarked == [], f"{slug}: sin marca {unmarked}"
    # La marca es un concepto del vocabulario, con etiqueta.
    label = _sparql(
        stack,
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> "
        f"SELECT ?l WHERE {{ GRAPH ?g {{ <{marker}> a skos:Concept ; skos:prefLabel ?l }} }}",
    )
    assert [row["l"]["value"] for row in label] == ["Dataset sintético"]

    # En la API y en el RDF servido.
    assert all(item["synthetic"] for item in _datasets(stack)["items"] if item["slug"] in SYNTHETIC)
    for slug in SYNTHETIC:
        detail = http("GET", f"{stack.api}/datasets/{slug}").json()
        assert detail["synthetic"] is True
        for entry in detail["versions"]:
            if not entry["described"]:
                continue
            query = f"format=turtle&version={entry['version']}"
            rdf = http("GET", f"{stack.api}/datasets/{slug}/rdf?{query}")
            assert rdf.status == 200
            assert "tipo-dataset/sintetico" in rdf.text, f"{slug} {entry['version']}"
        series = http("GET", f"{stack.api}/dataset/{slug}", headers={"Accept": "text/turtle"})
        assert series.text.count("tipo-dataset/sintetico") >= 1 + sum(
            1 for entry in detail["versions"] if entry["described"]
        )


# --- 6. URIs persistentes --------------------------------------------------------------


def test_la_uri_persistente_redirige_303_a_la_ficha_del_frontend(stack: Stack, loaded: str) -> None:
    html = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}  # un navegador
    frontend = stack.env["FRONTEND_BASE_URL"]

    series = http(
        "GET",
        f"{stack.api}/dataset/modbus-tcp-testbed",
        headers=html,
        follow_redirects=False,
    )
    assert series.status == 303
    assert series.headers["location"] == f"{frontend}/datasets/modbus-tcp-testbed"
    assert "Accept" in series.headers.get("vary", "")

    version = http(
        "GET",
        f"{stack.api}/dataset/modbus-tcp-testbed/1.0.0",
        headers=html,
        follow_redirects=False,
    )
    assert version.status == 303
    assert version.headers["location"] == f"{frontend}/datasets/modbus-tcp-testbed?version=1.0.0"

    # El destino existe: el frontend sirve la aplicación en esa ruta.
    for location in (series.headers["location"], version.headers["location"]):
        target = location.replace("http://localhost:", "http://127.0.0.1:")
        page = wait_for_http(target)
        assert page.status == 200, target
        assert '<div id="root">' in page.text

    # Lo que no existe da 404 también cuando se pide HTML (no redirige a una ficha vacía).
    for path in ("/dataset/no-existe", "/dataset/modbus-tcp-testbed/9.9.9"):
        missing = http("GET", f"{stack.api}{path}", headers=html, follow_redirects=False)
        assert missing.status == 404, path


def test_la_uri_persistente_sirve_rdf_por_negociacion(stack: Stack, loaded: str) -> None:
    base = _base_uri(stack)
    url = f"{stack.api}/dataset/modbus-tcp-testbed"
    # Fase 4 (decisión 31): sin Accept o con */* es un 303 al HTML, no Turtle.
    for accept in (None, "*/*"):
        see_other = http(
            "GET",
            url,
            headers={"Accept": accept} if accept else {},
            follow_redirects=False,
        )
        assert see_other.status == 303, accept
        assert see_other.headers["location"].startswith(stack.frontend_origin + "/")
    for accept, media in (
        ("text/turtle", "text/turtle"),
        ("application/ld+json", "application/ld+json"),
    ):
        response = http("GET", url, headers={"Accept": accept})
        assert response.status == 200, accept
        assert response.headers["content-type"].startswith(media), accept
    series = http("GET", url, headers={"Accept": "text/turtle"}).text
    # La serie completa trae todas sus versiones; la URI de una versión, solo la suya.
    assert all(f'"{version}"' in series for version in MODBUS_VERSIONS)
    one = http("GET", f"{url}/2.0.0", headers={"Accept": "text/turtle"}).text
    assert '"2.0.0"' in one and '"1.0.0"' not in one
    assert f"{base}dataset/" in series or "itotd:" in series
    assert http("GET", url, headers={"Accept": "image/png"}).status == 406


# --- 7. Publicación por la API ---------------------------------------------------------


def test_solo_editor_y_admin_publican(
    stack: Stack, loaded: str, g2_member: Account, g2_editor: Account
) -> None:
    before = _graphs(stack)
    slug = f"e2e-denegado-{secrets.token_hex(3)}"
    body = _series_ttl(slug, "No debe publicarse")
    assert _publish(stack, body, None).status == 401
    assert _publish(stack, body, g2_member.token).status == 403
    assert _publish(stack, body, "no-es-un-token").status == 401
    assert _graphs(stack) == before
    assert http("GET", f"{stack.api}/datasets/{slug}").status == 404


def test_un_editor_publica_y_el_dataset_aparece_en_el_catalogo(
    stack: Stack, published: dict, g2_editor: Account
) -> None:
    base = _base_uri(stack)
    slug, title = published["slug"], published["title"]
    series_uri = f"{base}dataset/{slug}"
    assert published["body"] == {
        "slug": slug,
        "uri": series_uri,
        "graph": series_uri,
        "versions": ["1.0.0"],
        "triples": published["body"]["triples"],
        "created": True,
        "changed": True,
    }
    # En el triplestore, en su propio grafo.
    assert _graphs(stack)[series_uri] == published["body"]["triples"]

    # En el catálogo, con sus filtros.
    page = _datasets(stack)
    assert page["total"] == 4
    card = next(item for item in page["items"] if item["slug"] == slug)
    assert card["title"] == title
    assert card["current_version"] == "1.0.0"
    assert card["domain"]["slug"] == "ot"
    assert card["formats"] == ["text/csv"]
    assert card["access_rights"]["code"] == "PUBLIC"
    assert card["synthetic"] is True
    assert slug in _slugs(stack, domain="ot")
    assert slug not in _slugs(stack, domain="it")
    assert _slugs(stack, q=slug) == [slug]

    # Ficha, RDF y URI persistente.
    detail = http("GET", f"{stack.api}/datasets/{slug}")
    assert detail.status == 200
    assert detail.json()["version"]["distributions"][0]["access_url"] == (f"{series_uri}/1.0.0/csv")
    assert title in http("GET", f"{stack.api}/datasets/{slug}/rdf?format=turtle").text
    redirect = http(
        "GET",
        f"{stack.api}/dataset/{slug}",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert redirect.status == 303
    assert redirect.headers["location"] == f"{stack.env['FRONTEND_BASE_URL']}/datasets/{slug}"

    # En la auditoría, con el editor como actor.
    (event,) = [e for e in _published_events(stack) if e["details"]["slug"] == slug]
    assert event["actor_username"] == g2_editor.username
    assert event["actor_id"] == g2_editor.id
    assert event["details"]["via"] == "api"
    assert event["details"]["created"] is True


def test_republicar_sustituye_la_serie_y_el_admin_hereda_del_editor(
    stack: Stack, published: dict, g2_editor: Account, admin: Account
) -> None:
    slug, title = published["slug"], published["title"]
    same = _publish(stack, _series_ttl(slug, title), g2_editor.token)
    assert same.status == 200, same.text
    assert (same.json()["created"], same.json()["changed"]) == (False, False)

    # El admin hereda los permisos de editor (decisión 16) y publica una versión nueva.
    # Fase 4 (decisión 28): las versiones son inmutables y la serie se envía con todas ellas,
    # así que la 1.0.0 viaja idéntica; los metadatos de la serie sí pueden cambiar.
    new_title = f"{title} (revisada)"
    original = _series_ttl(slug, title)
    old_version = original[original.index(f"<dataset/{slug}/1.0.0> a dcat:Dataset") :]
    newer = _series_ttl(slug, new_title, version="1.1.0", extra=old_version)
    replaced = _publish(stack, newer, admin.token)
    assert replaced.status == 200, replaced.text
    assert (replaced.json()["created"], replaced.json()["changed"]) == (False, True)
    detail = http("GET", f"{stack.api}/datasets/{slug}").json()
    assert detail["title"] == new_title
    assert detail["current_version"] == "1.1.0"
    # La 1.0.0 sigue publicada y sin cambios.
    assert [v["version"] for v in detail["versions"]] == ["1.1.0", "1.0.0"]
    old = http("GET", f"{stack.api}/datasets/{slug}?version=1.0.0")
    assert old.status == 200 and old.json()["version"]["title"] == title

    events = [e for e in _published_events(stack) if e["details"]["slug"] == slug]
    assert [e["actor_username"] for e in events] == [
        g2_editor.username,
        g2_editor.username,
        admin.username,
    ]
    assert [e["details"]["changed"] for e in events] == [True, False, True]
    # Las tres series sintéticas siguen intactas.
    assert [s for s in _slugs(stack) if s in SYNTHETIC] == sorted(SYNTHETIC)


def test_publicar_en_json_ld(stack: Stack, loaded: str, g2_editor: Account) -> None:
    base = _base_uri(stack)
    slug = f"e2e-jsonld-{secrets.token_hex(3)}"
    series, version = f"{base}dataset/{slug}", f"{base}dataset/{slug}/1.0.0"
    text = {
        "@language": "es",
        "@value": "Serie JSON-LD de la prueba de extremo a extremo",
    }
    document = {
        "@context": {
            "dcat": "http://www.w3.org/ns/dcat#",
            "dct": "http://purl.org/dc/terms/",
        },
        "@graph": [
            # Decisión 49: la pertenencia al catálogo viaja en el grafo que se ingesta.
            {"@id": f"{base}catalogo/e2e-pruebas", "dcat:dataset": {"@id": series}},
            {
                "@id": series,
                "@type": "dcat:DatasetSeries",
                "dct:type": {"@id": f"{base}vocab/tipo-dataset/sintetico"},
                "dct:title": text,
                "dct:description": text,
            },
            {
                "@id": version,
                "@type": "dcat:Dataset",
                "dct:type": {"@id": f"{base}vocab/tipo-dataset/sintetico"},
                "dct:title": text,
                "dct:description": text,
                "dcat:version": "1.0.0",
                "dcat:inSeries": {"@id": series},
                "dct:accessRights": {"@id": PUBLIC},
                "dcat:distribution": {"@id": f"{version}/csv"},
            },
            {
                "@id": f"{version}/csv",
                "@type": "dcat:Distribution",
                "dcat:accessURL": {"@id": f"{version}/csv"},
            },
        ],
    }
    response = _publish(stack, json.dumps(document), g2_editor.token, JSONLD)
    assert response.status == 201, response.text
    detail = http("GET", f"{stack.api}/datasets/{slug}").json()
    assert detail["title"] == text["@value"]
    assert detail["synthetic"] is True


# --- 8. Rechazos de la ingesta ---------------------------------------------------------


def test_la_ingesta_que_no_cumple_shacl_se_rechaza_con_422(
    stack: Stack, loaded: str, g2_editor: Account
) -> None:
    before = _graphs(stack)
    events = len(_published_events(stack))
    base = _base_uri(stack)

    invalid = (INVALID_DIR / "dataset-sin-titulo.ttl").read_bytes()
    response = _publish(stack, invalid, g2_editor.token)
    assert response.status == 422, response.text
    body = response.json()
    assert body["kind"] == "shacl"
    assert body["report"]
    (issue,) = body["issues"]
    assert issue["source_shape"] == f"{base}shapes#Dataset-title"
    assert issue["focus_node"] == f"{base}dataset/prueba/1.0.0"
    assert issue["path"] == "http://purl.org/dc/terms/title"

    # Todos los ejemplos inválidos del contrato se rechazan igual.
    for path in sorted(INVALID_DIR.glob("*.ttl")):
        rejected = _publish(stack, path.read_bytes(), g2_editor.token)
        assert rejected.status == 422, path.name
        assert rejected.json()["issues"], path.name

    # Nada se ha escrito ni auditado.
    assert _graphs(stack) == before
    assert len(_published_events(stack)) == events
    assert http("GET", f"{stack.api}/datasets/prueba").status == 404


def test_la_ingesta_no_escribe_fuera_de_su_serie(
    stack: Stack, loaded: str, g2_editor: Account
) -> None:
    before = _graphs(stack)
    slug = f"e2e-intruso-{secrets.token_hex(3)}"
    for extra in (
        '<dataset/modbus-tcp-testbed> dct:title "Secuestrada"@es .',
        '<dataset/modbus-tcp-testbed/2.1.0> dct:title "Secuestrada"@es .',
        '<catalogo> dct:title "Secuestrado"@es .',
        '<vocab/ot/modbus-tcp> <http://www.w3.org/2004/02/skos/core#prefLabel> "Falsa"@es .',
        '<https://otro.example/recurso> dct:title "Ajeno"@es .',
    ):
        response = _publish(stack, _series_ttl(slug, "Intruso", extra=extra), g2_editor.token)
        assert response.status == 422, extra
        assert response.json()["kind"] == "uri", extra
    assert _graphs(stack) == before
    assert "Secuestrada" not in http("GET", f"{stack.api}/datasets/modbus-tcp-testbed").text
    assert http("GET", f"{stack.api}/datasets/{slug}").status == 404


def test_la_ingesta_rechaza_sintaxis_tipos_y_contextos_remotos(
    stack: Stack, loaded: str, g2_editor: Account
) -> None:
    before = _graphs(stack)
    token = g2_editor.token
    slug = f"e2e-raro-{secrets.token_hex(3)}"
    body = _series_ttl(slug, "No debe publicarse")
    assert _publish(stack, "esto no es turtle <", token).status == 422
    assert _publish(stack, "DROP ALL", token).status == 422
    assert _publish(stack, body, token, JSONLD).status == 422  # Turtle declarado como JSON-LD
    for content_type in (
        "text/plain",
        "application/sparql-update",
        "application/n-quads",
    ):
        assert _publish(stack, body, token, {"Content-Type": content_type}).status == 415

    # Contexto JSON-LD remoto: se rechaza sin que el backend salga a buscarlo. El destino
    # es el endpoint SPARQL del propio Fuseki del entorno, que registra cada consulta en su
    # log (una ruta cualquiera de Fuseki no queda registrada: por eso hay una de control).
    probe = f"qa-ssrf-{secrets.token_hex(6)}"
    remote = {
        "@context": fuseki_probe_url(stack, probe),
        "@id": f"dataset/{slug}",
    }
    response = _publish(stack, json.dumps(remote), token, JSONLD)
    assert response.status == 422
    assert "contextos remotos" in response.json()["detail"]
    assert not fuseki_logged(stack, probe)
    control = f"qa-control-{secrets.token_hex(6)}"
    http("GET", fuseki_probe_url(stack, control, from_host=True))
    assert fuseki_logged(stack, control), "el log de Fuseki no registra las consultas"

    assert _graphs(stack) == before
    assert http("GET", f"{stack.api}/datasets/{slug}").status == 404


def test_la_ingesta_rechaza_cuerpos_por_encima_del_limite(stack: Stack, g2_editor: Account) -> None:
    """Con un ``Content-Length`` un byte por encima de ``INGEST_MAX_BYTES`` el backend
    responde 413 sin esperar al cuerpo (no se envía ninguno)."""
    connection = HTTPConnection("127.0.0.1", stack.ports["backend"], timeout=15)
    try:
        connection.putrequest("POST", "/datasets")
        connection.putheader("Content-Type", "text/turtle")
        connection.putheader("Content-Length", str(INGEST_MAX_BYTES + 1))
        connection.putheader("Authorization", f"Bearer {g2_editor.token}")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413, response.read()[:300]
    finally:
        connection.close()


def test_la_ingesta_rechaza_iris_no_validas_con_422(
    stack: Stack, loaded: str, g2_editor: Account
) -> None:
    slug = f"e2e-iri-{secrets.token_hex(3)}"
    statuses = {}
    for name, bad in (
        ("espacio", "<http://x.example/a b>"),
        ("salto de línea", "<http://x.example/a\\u000Ab>"),
    ):
        extra = f"<dataset/{slug}> dct:relation {bad} ."
        response = _publish(stack, _series_ttl(slug, "IRI no válida", extra=extra), g2_editor.token)
        statuses[name] = response.status
    assert statuses == {"espacio": 422, "salto de línea": 422}


# --- 9. Cierre -------------------------------------------------------------------------


def test_la_auditoria_y_los_logs_no_contienen_secretos(stack: Stack, published: dict) -> None:
    dump = "\n".join(stack.psql("select row_to_json(a) from audit_events a order by a.id"))
    result = stack.compose("logs", "--no-color", "--no-log-prefix", timeout=120)
    assert result.returncode == 0, result.stderr
    logs = result.stdout + result.stderr
    assert dump and logs.strip()
    for name, secret in stack.sensitive.items():
        assert secret not in dump, f"audit_events contiene {name}"
        assert secret not in logs, f"los logs contienen {name}"
    # Tampoco la cabecera Basic con la que el backend escribe en Fuseki.
    basic = base64.b64encode(
        f"{stack.env['FUSEKI_USER']}:{stack.env['FUSEKI_BACKEND_PASSWORD']}".encode()
    ).decode()
    assert basic not in logs
    assert basic not in dump


def test_la_api_no_expone_las_credenciales_de_fuseki(stack: Stack, published: dict) -> None:
    password = stack.env["FUSEKI_ADMIN_PASSWORD"]
    for path in (
        "/openapi.json",
        "/health/ready",
        "/datasets",
        f"/datasets/{published['slug']}",
    ):
        response = http("GET", f"{stack.api}{path}")
        assert response.status == 200, path
        assert password not in response.text, path
        assert "FUSEKI_PASSWORD" not in response.text, path


def test_fuseki_sigue_sin_admitir_escrituras_anonimas(stack: Stack, published: dict) -> None:
    """Tras la fase 2 la regla sigue en pie: solo el backend escribe en el triplestore."""
    base = _base_uri(stack)
    graph = f"{base}dataset/{published['slug']}"
    endpoint = f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}"
    before = _graphs(stack)
    quoted = urllib.parse.quote(graph, safe="")
    assert http("DELETE", f"{endpoint}/data?graph={quoted}").status == 401
    put = http(
        "PUT",
        f"{endpoint}/data?graph={quoted}",
        raw_body=b"<urn:qa:s> <urn:qa:p> <urn:qa:o> .",
        headers=TURTLE,
    )
    assert put.status == 401
    drop = http("POST", f"{endpoint}/update", form={"update": f"DROP GRAPH <{graph}>"})
    assert drop.status == 401
    assert _graphs(stack) == before


def test_el_entorno_sigue_sano_tras_la_fase_2(stack: Stack) -> None:
    ready = http("GET", f"{stack.api}/health/ready")
    assert ready.status == 200, ready.text
    restarts = stack.compose("ps", "--all", "--format", "{{.Service}} {{.Status}}").stdout
    assert "Restarting" not in restarts
    assert "unhealthy" not in restarts
