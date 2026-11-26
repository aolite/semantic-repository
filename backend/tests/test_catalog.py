"""Lectura pública del catálogo: tarjetas, filtros, ficha, RDF e intentos de inyección.

Se usa ``MemoryStore`` (rdflib) con los datos sintéticos de G2 cargados como lo haría
``load-semantic``: el vocabulario en su grafo y cada serie en el suyo.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic

from app import ingest
from app.models import Role
from app.triplestore import MemoryStore
from app.uris import SKOS, Uris
from tests.conftest import BASE_URI, REPO_SEMANTIC_DIR

MODBUS = f"{BASE_URI}dataset/modbus-tcp-testbed"
RESTRICTED = "http://publications.europa.eu/resource/authority/access-right/RESTRICTED"


@pytest.fixture
def api(client: TestClient, loaded_store: MemoryStore) -> TestClient:
    return client


# --- GET /datasets --------------------------------------------------------------------


def test_list_returns_cards(api: TestClient) -> None:
    response = api.get("/datasets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    slugs = [c["slug"] for c in body["items"]]
    assert sorted(slugs) == [
        "ejemplos-adversarios-vision",
        "hallazgos-auditorias-intrusion",
        "modbus-tcp-testbed",
    ]
    card = next(c for c in body["items"] if c["slug"] == "modbus-tcp-testbed")
    assert card == {
        "slug": "modbus-tcp-testbed",
        "uri": MODBUS,
        "title": "Tráfico Modbus/TCP del banco de pruebas OT",
        "description": card["description"],
        "catalog": {  # decisión 49
            "slug": "sintetico",
            "uri": f"{BASE_URI}catalogo/sintetico",
            "title": "Datasets sintéticos de demostración",
        },
        "domain": {"slug": "ot", "uri": f"{BASE_URI}vocab/dominio/ot", "label": "OT / ICS"},
        "domains": [{"slug": "ot", "uri": f"{BASE_URI}vocab/dominio/ot", "label": "OT / ICS"}],
        "themes": [
            {
                "uri": f"{BASE_URI}vocab/ot/modbus-tcp",
                "label": "Modbus/TCP",
                "scheme": f"{BASE_URI}vocab/ot",
            },
            {
                "uri": f"{BASE_URI}vocab/ot/purdue-nivel-1",
                "label": "Nivel 1 · Control básico",
                "scheme": f"{BASE_URI}vocab/ot",
            },
        ],
        "access_rights": {"uri": RESTRICTED, "code": "RESTRICTED"},
        "formats": ["text/csv", "application/vnd.apache.parquet", "application/vnd.tcpdump.pcap"],
        "current_version": "2.1.0",
        "synthetic": True,
        "fair_total": None,  # fase 4: sin evaluación FAIR terminada
    }
    assert card["description"].startswith("Capturas de red etiquetadas")


def test_format_falls_back_to_distribution_title(api: TestClient) -> None:
    cards = api.get("/datasets").json()["items"]
    vision = next(c for c in cards if c["slug"] == "ejemplos-adversarios-vision")
    assert vision["formats"] == ["application/json", "NPZ"]
    assert vision["domain"]["slug"] == "ia"


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("ot", ["modbus-tcp-testbed"]),
        ("it", ["hallazgos-auditorias-intrusion"]),
        ("ia", ["ejemplos-adversarios-vision"]),
        ("pqc", []),
    ],
)
def test_filter_by_domain(api: TestClient, domain: str, expected: list[str]) -> None:
    body = api.get("/datasets", params={"domain": domain}).json()
    assert [c["slug"] for c in body["items"]] == expected
    assert body["total"] == len(expected)


def test_unknown_domain_is_422(api: TestClient) -> None:
    assert api.get("/datasets", params={"domain": "defensa"}).status_code == 422


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("modbus", ["modbus-tcp-testbed"]),  # título
        ("MODBUS", ["modbus-tcp-testbed"]),  # sin mayúsculas
        ("deteccion de intrusiones", []),  # palabra clave: no se busca en keywords
        ("supervision", ["modbus-tcp-testbed"]),  # descripción, sin acentos
        ("caja blanca", ["ejemplos-adversarios-vision"]),  # etiqueta de tema
        ("cwe", ["hallazgos-auditorias-intrusion"]),
        ("no-existe-nada", []),
    ],
)
def test_filter_by_text(api: TestClient, q: str, expected: list[str]) -> None:
    body = api.get("/datasets", params={"q": q}).json()
    assert [c["slug"] for c in body["items"]] == expected


def test_text_and_domain_combined(api: TestClient) -> None:
    body = api.get("/datasets", params={"q": "modbus", "domain": "it"}).json()
    assert body["items"] == []


def test_pagination(api: TestClient) -> None:
    first = api.get("/datasets", params={"page_size": 2}).json()
    second = api.get("/datasets", params={"page_size": 2, "page": 2}).json()
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    seen = {c["slug"] for c in first["items"]} | {c["slug"] for c in second["items"]}
    assert len(seen) == 3
    assert api.get("/datasets", params={"page_size": 0}).status_code == 422
    assert api.get("/datasets", params={"page_size": 101}).status_code == 422
    assert api.get("/datasets", params={"page": 0}).status_code == 422


def test_empty_catalog(client: TestClient) -> None:
    assert client.get("/datasets").json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
    }


INJECTIONS = [
    '" } UNION { ?s ?p ?o } #',
    "') } ; DROP ALL ; #",
    "\\u0022 } INSERT DATA { <urn:a> <urn:b> <urn:c> } #",
    'modbus" . FILTER(true) #',
    "}}}}{{{{",
]


@pytest.mark.parametrize("q", INJECTIONS)
def test_injection_in_q_is_inert(api: TestClient, loaded_store: MemoryStore, q: str) -> None:
    before = len(loaded_store.dataset)
    response = api.get("/datasets", params={"q": q})
    assert response.status_code == 200
    assert response.json()["total"] == 0
    # q no llega a SPARQL y el triplestore no cambia.
    assert all(q not in query for query in loaded_store.queries)
    assert len(loaded_store.dataset) == before


# --- GET /datasets/{slug} -------------------------------------------------------------


def test_detail_current_version(api: TestClient) -> None:
    response = api.get("/datasets/modbus-tcp-testbed")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "modbus-tcp-testbed"
    assert body["uri"] == MODBUS
    assert body["synthetic"] is True
    assert body["current_version"] == "2.1.0"
    assert body["domain"]["slug"] == "ot"
    version = body["version"]
    assert version["uri"] == f"{MODBUS}/2.1.0"
    assert version["version"] == "2.1.0"
    assert version["version_notes"] == "Características por flujo en Parquet; etiquetas corregidas."
    assert version["previous_version"] == {"uri": f"{MODBUS}/2.0.0", "version": "2.0.0"}
    assert version["in_series"] == MODBUS
    assert version["synthetic"] is True
    assert version["keywords"] == [
        "ICS",
        "Modbus",
        "detección de intrusiones",
        "tráfico industrial",
    ]
    dists = {d["uri"].rsplit("/", 1)[-1]: d for d in version["distributions"]}
    assert set(dists) == {"pcap", "csv", "parquet"}
    assert dists["pcap"] == {
        "uri": f"{MODBUS}/2.1.0/pcap",
        "title": "Capturas en bruto",
        "media_type": "application/vnd.tcpdump.pcap",
        "media_type_uri": "http://www.iana.org/assignments/media-types/application/vnd.tcpdump.pcap",
        "access_url": f"{MODBUS}/2.1.0/pcap",
        "access_rights": {"uri": RESTRICTED, "code": "RESTRICTED"},
        # Fase 4: sin fichero subido.
        "download": "unavailable",
        "download_url": None,
        "byte_size": None,
        "sha256": None,
    }
    assert [(s["kind"], s["label"]) for s in version["provenance"]] == [
        ("activity", "Captura en banco de pruebas"),
        ("entity", "Capturas PCAP en bruto"),
        ("activity", "Extracción de características y etiquetado"),
    ]
    assert version["provenance"][0]["uri"] is None
    assert version["provenance"][2]["uri"] == f"{BASE_URI}actividad/extraccion-caracteristicas"
    assert version["provenance"][2]["agents"] == [
        {"uri": None, "label": "Eurecat · Unidad IT&OT Security"}
    ]
    meta = version["metadata"]
    assert meta["publisher"] == {"uri": None, "label": "Eurecat · Unidad IT&OT Security"}
    # Placeholders del prototipo: no están en el RDF, se devuelven como null.
    assert meta["contact_point"] is None
    assert meta["license"] is None
    assert meta["issued"] is None
    assert meta["modified"] is None
    assert meta["is_referenced_by"] == []
    assert meta["access_rights"]["code"] == "RESTRICTED"
    assert [t["label"] for t in meta["themes"]] == ["Modbus/TCP", "Nivel 1 · Control básico"]
    assert meta["conforms_to"] == [{"uri": f"{BASE_URI}onto/itot/1.2.0", "label": None}]
    # Fase 4: la evaluación FAIR sale solo de F-UJI; sin evaluación, no hay puntuación.
    assert body["version"]["fair"]["status"] == "not_evaluated"
    assert body["version"]["fair"]["total"] is None


def test_detail_history(api: TestClient) -> None:
    history = api.get("/datasets/modbus-tcp-testbed").json()["versions"]
    assert [(h["version"], h["current"], h["described"]) for h in history] == [
        ("2.1.0", True, True),
        ("2.0.0", False, True),
        ("1.0.0", False, True),
    ]
    assert history[2]["notes"].startswith("Publicación inicial")
    assert all(h["issued"] is None for h in history)


def test_detail_old_version_with_missing_data(api: TestClient) -> None:
    response = api.get("/datasets/modbus-tcp-testbed", params={"version": "2.0.0"})
    assert response.status_code == 200
    body = response.json()
    assert body["current_version"] == "2.1.0"
    assert body["domain"]["slug"] == "ot"  # el dominio es de la serie (dcat:last)
    version = body["version"]
    assert version["version"] == "2.0.0"
    assert version["distributions"] == []
    assert version["provenance"] == []
    assert version["metadata"]["themes"] == []
    assert version["keywords"] == []
    assert version["previous_version"]["version"] == "1.0.0"
    first = api.get("/datasets/modbus-tcp-testbed", params={"version": "1.0.0"}).json()
    assert first["version"]["previous_version"] is None
    assert len(first["version"]["distributions"]) == 2


@pytest.mark.usefixtures("synthetic_themes")
def test_detail_referenced_only_previous_version(
    client: TestClient, store: MemoryStore, semantic_dir: Path, uris: Uris
) -> None:
    # El ejemplo de semantic/examples/valid/ solo referencia la 2.0.0 y no tiene vocabulario.
    example = REPO_SEMANTIC_DIR / "examples" / "valid" / "modbus-tcp-testbed.ttl"
    graph = Graph().parse(example, format="turtle", publicID=BASE_URI)
    ingest.publish(store, ingest.prepare_series(graph, uris, semantic_dir))
    body = client.get("/datasets/modbus-tcp-testbed").json()
    assert [(h["version"], h["described"]) for h in body["versions"]] == [
        ("2.1.0", True),
        ("2.0.0", False),
    ]
    # Sin vocabulario cargado, el dominio sale del patrón de la URI del concepto.
    assert body["domain"] == {"slug": "ot", "uri": f"{BASE_URI}vocab/dominio/ot", "label": None}
    assert body["synthetic"] is False


def test_detail_not_found(api: TestClient) -> None:
    assert api.get("/datasets/no-existe").status_code == 404
    response = api.get("/datasets/modbus-tcp-testbed", params={"version": "9.9.9"})
    assert response.status_code == 404


@pytest.mark.parametrize("version", ["2.1", "v2.1.0", "2.1.0-rc.1", "2.1.0'}", "02.1.0"])
def test_detail_invalid_version_is_422(api: TestClient, version: str) -> None:
    response = api.get("/datasets/modbus-tcp-testbed", params={"version": version})
    assert response.status_code == 422


SLUG_INJECTIONS = [
    "modbus-tcp-testbed>%20%7D",
    "x%3E%20%7D%20UNION%20%7B%20%3Fs%20%3Fp%20%3Fo",
    "Modbus",
    "modbus_tcp",
    "-modbus",
    "modbus--tcp",
    "%22%3B%20DROP%20ALL",
    "a%0Ab",
]


@pytest.mark.parametrize("slug", SLUG_INJECTIONS)
def test_injection_in_slug_never_reaches_sparql(
    api: TestClient, loaded_store: MemoryStore, slug: str
) -> None:
    for path in (f"/datasets/{slug}", f"/datasets/{slug}/rdf", f"/dataset/{slug}"):
        response = api.get(path)
        assert response.status_code in (404, 422), path
    assert loaded_store.queries == []


# --- GET /datasets/{slug}/rdf ---------------------------------------------------------


def _version_graph(text: str, fmt: str) -> Graph:
    return Graph().parse(data=text, format=fmt)


@pytest.mark.parametrize(
    ("kwargs", "media", "fmt"),
    [
        ({"headers": {"Accept": "text/turtle"}}, "text/turtle", "turtle"),
        ({"headers": {"Accept": "application/ld+json"}}, "application/ld+json", "json-ld"),
        ({"params": {"format": "turtle"}}, "text/turtle", "turtle"),
        (
            {"params": {"format": "jsonld"}, "headers": {"Accept": "text/turtle"}},
            "application/ld+json",
            "json-ld",
        ),
        ({}, "text/turtle", "turtle"),
    ],
)
def test_rdf_formats(api: TestClient, kwargs: dict, media: str, fmt: str) -> None:
    response = api.get("/datasets/modbus-tcp-testbed/rdf", **kwargs)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media)
    graph = _version_graph(response.text, fmt)
    version = URIRef(f"{MODBUS}/2.1.0")
    assert (version, None, None) in graph
    # Solo la versión pedida: ni las otras versiones ni la serie se describen.
    assert (URIRef(f"{MODBUS}/2.0.0"), None, None) not in graph
    assert (URIRef(MODBUS), None, None) not in graph
    assert (URIRef(f"{MODBUS}/2.1.0/pcap"), None, None) in graph


def test_rdf_turtle_and_jsonld_are_equivalent(api: TestClient) -> None:
    ttl = api.get("/datasets/modbus-tcp-testbed/rdf", params={"format": "turtle"}).text
    jsonld = api.get("/datasets/modbus-tcp-testbed/rdf", params={"format": "jsonld"}).text
    assert isomorphic(_version_graph(ttl, "turtle"), _version_graph(jsonld, "json-ld"))


def test_rdf_of_old_version(api: TestClient) -> None:
    response = api.get(
        "/datasets/modbus-tcp-testbed/rdf", params={"version": "1.0.0", "format": "turtle"}
    )
    graph = _version_graph(response.text, "turtle")
    assert (URIRef(f"{MODBUS}/1.0.0"), None, None) in graph
    assert (URIRef(f"{MODBUS}/2.1.0"), None, None) not in graph


def test_rdf_not_acceptable(api: TestClient) -> None:
    response = api.get("/datasets/modbus-tcp-testbed/rdf", headers={"Accept": "application/xml"})
    assert response.status_code == 406
    assert api.get("/datasets/modbus-tcp-testbed/rdf", params={"format": "xml"}).status_code == 422


def test_rdf_not_found(api: TestClient) -> None:
    assert api.get("/datasets/no-existe/rdf").status_code == 404
    response = api.get("/datasets/modbus-tcp-testbed/rdf", params={"version": "9.9.9"})
    assert response.status_code == 404


# --- Errores del triplestore ----------------------------------------------------------


# --- QA-G2-04: solo grafos publicados ---------------------------------------------------

PRIVATE_GRAPH = f"{BASE_URI}privado/borrador"
PUBLIC = "http://publications.europa.eu/resource/authority/access-right/PUBLIC"
SECRET = "Texto de un grafo no publicado"
HIDDEN_SERIES = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct:  <http://purl.org/dc/terms/> .
<dataset/oculta> a dcat:DatasetSeries ; dct:title "TEXTO"@es ; dct:description "d"@es ;
    dcat:last <dataset/oculta/1.0.0> .
<dataset/oculta/1.0.0> a dcat:Dataset ; dct:title "TEXTO"@es ; dct:description "d"@es ;
    dcat:version "1.0.0" ; dcat:inSeries <dataset/oculta> .
<catalogo/pruebas> dcat:dataset <dataset/oculta> .
""".replace("TEXTO", SECRET)


def _public_text(client: TestClient) -> str:
    parts = [client.get("/datasets", params={"page_size": 100}).text]
    for slug in ("modbus-tcp-testbed", "hallazgos-auditorias-intrusion", "oculta", "prueba"):
        parts.append(client.get(f"/datasets/{slug}").text)
        parts.append(client.get(f"/datasets/{slug}/rdf").text)
    return "\n".join(parts)


def test_series_outside_its_own_graph_is_not_read(
    api: TestClient, loaded_store: MemoryStore
) -> None:
    hidden = Graph().parse(data=HIDDEN_SERIES, format="turtle", publicID=BASE_URI)
    loaded_store.put_graph(PRIVATE_GRAPH, hidden)
    # También en el grafo de OTRA serie publicada: no es el suyo.
    loaded_store.put_graph(f"{BASE_URI}dataset/otra", hidden)
    assert api.get("/datasets").json()["total"] == 3
    assert api.get("/datasets/oculta").status_code == 404
    assert api.get("/dataset/oculta").status_code == 404
    assert SECRET not in _public_text(api)


def test_theme_labels_come_only_from_the_vocabulary_graph(
    api: TestClient, loaded_store: MemoryStore, editor_headers_factory
) -> None:
    hidden = URIRef(f"{BASE_URI}interno/recurso")
    private = Graph()
    private.add((hidden, SKOS.prefLabel, Literal(SECRET, lang="es")))
    private.add((hidden, SKOS.inScheme, URIRef(f"{BASE_URI}vocab/ot")))
    loaded_store.put_graph(PRIVATE_GRAPH, private)
    series = (
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n"
        "@prefix dct: <http://purl.org/dc/terms/> .\n"
        '<dataset/prueba> a dcat:DatasetSeries ; dct:title "P"@es ; dct:description "d"@es ;\n'
        "    dcat:last <dataset/prueba/1.0.0> .\n"
        '<dataset/prueba/1.0.0> a dcat:Dataset ; dct:title "P"@es ; dct:description "d"@es ;\n'
        '    dcat:version "1.0.0" ; dcat:inSeries <dataset/prueba> ;\n'
        f"    dct:accessRights <{PUBLIC}> ;\n"
        f"    dcat:theme <{hidden}> .\n"
        "<catalogo/pruebas> dcat:dataset <dataset/prueba> .\n"
    )
    response = api.post(
        "/datasets", content=series.encode(), headers=editor_headers_factory() | TURTLE_CT
    )
    assert response.status_code == 201, response.text
    assert SECRET not in _public_text(api)
    assert api.get("/datasets", params={"q": SECRET}).json()["total"] == 0
    card = next(c for c in api.get("/datasets").json()["items"] if c["slug"] == "prueba")
    assert card["themes"] == [{"uri": str(hidden), "label": None, "scheme": None}]
    assert card["domain"] is None  # el inScheme del grafo privado tampoco cuenta


def test_read_queries_name_their_graphs(api: TestClient, loaded_store: MemoryStore) -> None:
    api.get("/datasets")
    api.get("/datasets/modbus-tcp-testbed")
    for query in loaded_store.queries:
        assert "GRAPH ?g " not in query and "GRAPH ?g2" not in query and "GRAPH ?g3" not in query


TURTLE_CT = {"Content-Type": "text/turtle"}


@pytest.fixture
def editor_headers_factory(make_user, login):
    def _factory() -> dict[str, str]:
        make_user("editora", Role.EDITOR)
        return login("editora")

    return _factory


def test_triplestore_down_gives_503(client: TestClient) -> None:
    from app.deps import get_triplestore
    from app.triplestore import TriplestoreError

    class Down:
        def construct(self, query: str) -> Graph:
            raise TriplestoreError("Fuseki no responde (ConnectError)")

    client.app.dependency_overrides[get_triplestore] = lambda: Down()
    response = client.get("/datasets")
    assert response.status_code == 503
    assert response.json() == {"detail": "Fuseki no responde (ConnectError)"}
