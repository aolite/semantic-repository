"""Lectura pública de ontologías y esquemas SKOS (fase 3) y nuevo cálculo de dominio.

Datos: copia de semantic/vocabularios, semantic/ontologias y data/vocab-minimo.ttl de
semantico (ver ``tests/conftest.py``).
"""

import json

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF

from app import ingest
from app.triplestore import MemoryStore
from app.uris import DCT, SKOS, Uris
from tests.conftest import BASE_URI, FIXTURE_DATA_DIR

ONTO = f"{BASE_URI}onto/itot"
OT = f"{BASE_URI}vocab/ot"
OT_TITLE = "Protocolos y arquitectura OT"
DOMINIO_OT = {"slug": "ot", "uri": f"{BASE_URI}vocab/dominio/ot", "label": "OT / ICS"}
D3F = "http://d3fend.mitre.org/ontologies/d3fend.owl"


@pytest.fixture
def api(client: TestClient, vocab_store: MemoryStore, vocab_metrics: None) -> TestClient:
    return client


# --- GET /vocabularies ----------------------------------------------------------------


def test_vocabularies_cards_and_counts(api: TestClient, itot_metrics: tuple[dict, dict]) -> None:
    response = api.get("/vocabularies")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {"own": 3, "external": 3, "skos_corp": 4, "skos_domain": 5}
    assert body["total"] == 15
    kinds = [c["kind"] for c in body["items"]]
    assert kinds == sorted(kinds, key=["own", "external", "skos_corp", "skos_domain"].index)
    cards = {c["uri"]: c for c in body["items"]}
    assert cards[ONTO] == {
        "kind": "own",
        "slug": "itot",
        "uri": ONTO,
        "rdf_type": "owl:Ontology",
        "title": "Ontología de activos y amenazas IT/OT",
        "prefix": "itot",
        "namespace": f"{ONTO}#",
        "description": cards[ONTO]["description"],
        "status": "published",
        "version": "1.2.0",
        "metrics": {
            "classes": itot_metrics[0]["classes"],
            "properties": itot_metrics[0]["object_properties"] + itot_metrics[0]["data_properties"],
        },
        "concepts": None,
        "domain": None,
        "synthetic": True,
    }
    pqcm = cards[f"{BASE_URI}onto/pqcm"]
    assert (pqcm["status"], pqcm["version"], pqcm["metrics"]) == ("draft", "0.4.0", None)
    saref = cards["https://saref.etsi.org/core/"]
    assert saref["kind"] == "external"
    assert saref["slug"] is None
    assert saref["status"] == "referenced"
    assert saref["prefix"] == "saref"
    assert saref["namespace"] == "https://saref.etsi.org/core/"
    assert saref["version"] == "3.2.1"
    assert saref["metrics"] is None and saref["concepts"] is None
    assert cards[D3F]["version"] is None  # [VERSIÓN]: placeholder, no está en el RDF
    trl = cards[f"{BASE_URI}vocab/corp/trl"]
    assert (trl["kind"], trl["slug"], trl["status"], trl["concepts"]) == (
        "skos_corp",
        "trl",
        "published",
        9,
    )
    assert trl["rdf_type"] == "skos:ConceptScheme"
    assert trl["synthetic"] is True
    assert cards[f"{BASE_URI}vocab/corp/sectores"]["status"] == "draft"
    ot = cards[OT]
    assert (ot["kind"], ot["slug"], ot["prefix"], ot["concepts"]) == ("skos_domain", "ot", "ot", 16)
    assert ot["title"] == OT_TITLE
    assert ot["namespace"] == f"{OT}/"
    assert ot["version"] == "1.0"
    # Los esquemas auxiliares no tienen tarjeta.
    assert f"{BASE_URI}vocab/dominio" not in cards
    assert f"{BASE_URI}vocab/tipo-dataset" not in cards


def test_vocabularies_without_metrics(client: TestClient, vocab_store: MemoryStore) -> None:
    cards = [c for c in client.get("/vocabularies").json()["items"] if c["kind"] == "own"]
    assert all(c["metrics"] is None for c in cards)


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("saref", {"https://saref.etsi.org/core/"}),
        # Fase 4 (decisión 30): q busca en la URI del recurso, no en su espacio de nombres.
        ("onto/itot#", set()),
        ("onto/itot", {ONTO}),
        ("MADUREZ TECNOLOGICA", {f"{BASE_URI}vocab/corp/trl"}),  # sin acentos ni mayúsculas
        ("ectrl", {f"{BASE_URI}vocab/corp/trl"}),
        ("nada-que-coincida", set()),
    ],
)
def test_vocabularies_filter_q(
    api: TestClient, vocab_store: MemoryStore, q: str, expected: set[str]
) -> None:
    body = api.get("/vocabularies", params={"q": q}).json()
    assert {c["uri"] for c in body["items"]} == expected
    assert body["total"] == len(expected)
    assert body["counts"]["skos_domain"] == 5  # los recuentos no dependen de q
    assert all(q not in query for query in vocab_store.queries)


def test_vocabularies_filter_kind(api: TestClient) -> None:
    body = api.get("/vocabularies", params={"kind": "skos_corp"}).json()
    assert [c["slug"] for c in body["items"]] == [
        "organizacion",
        "trl",
        "financiacion",
        "sectores",
    ]  # por título
    assert body["counts"]["own"] == 3
    assert api.get("/vocabularies", params={"kind": "otro"}).status_code == 422


# --- GET /ontologies/{slug} --------------------------------------------------------------


def test_ontology_detail(api: TestClient, itot_metrics: tuple[dict, dict]) -> None:
    response = api.get("/ontologies/itot")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == "itot"
    assert body["uri"] == ONTO
    assert body["kind"] == "own"
    assert body["status"] == "published"
    assert body["synthetic"] is True
    assert body["title"] == "Ontología de activos y amenazas IT/OT"
    # Las cifras salen del cálculo sobre el fichero (no se fijan aquí: semantico puede
    # cambiar el contenido de la ontología de demostración).
    computed = itot_metrics[0]
    assert body["metrics"] == {
        key: computed[key]
        for key in (
            "classes",
            "object_properties",
            "data_properties",
            "annotation_properties",
            "individuals",
            "logical_axioms",
            "imports",
        )
    } | {"dl_expressivity": None}
    assert body["profile"]["name"] == computed["profile"]
    assert body["profile"]["approximate"] is True
    expected = itot_metrics[1]
    assert body["consistency"]["reasoner"] == "Pellet"
    assert body["consistency"]["consistent"] == expected["consistent"]
    assert body["consistency"]["includes_imports"] is False
    assert body["documentation"]["percent"] == computed["documentation"]["percent"]
    assert body["metrics_tool"] == "owlready2 (pruebas)"
    assert body["metrics_computed_at"]

    meta = body["metadata"]
    assert meta["prefix"] == "itot"
    assert meta["namespace"] == f"{ONTO}#"
    assert meta["publisher"] == {"uri": None, "label": "Eurecat · Unidad IT&OT Security"}
    assert meta["creators"] == []  # [AUTORES]: placeholder
    assert meta["license"] is None  # [LICENCIA]: placeholder

    versioning = body["versioning"]
    assert versioning["version"] == "1.2.0"
    assert versioning["version_iri"] == f"{ONTO}/1.2.0"
    assert versioning["current_version"] == "1.2.0"
    assert versioning["prior_version"] == {"version_iri": f"{ONTO}/1.1.0", "version": "1.1.0"}
    assert versioning["backward_compatible_with"] == [
        {"version_iri": f"{ONTO}/1.1.0", "version": "1.1.0"}
    ]
    history = versioning["history"]
    assert [(h["version"], h["current"], h["described"]) for h in history] == [
        ("1.2.0", True, True),
        ("1.1.0", False, True),
        ("1.0.0", False, True),
    ]
    assert history[2]["notes"] == "Publicación inicial: activos, amenazas y controles."

    imports = {i["prefix"]: i for i in body["imports"]}
    assert set(imports) == {"sosa", "saref"}
    assert imports["saref"] == {
        "uri": "https://saref.etsi.org/core/",
        "title": "SAREF · Smart Applications REFerence ontology",
        "prefix": "saref",
        "version": "3.2.1",
        "known": True,
    }

    [use] = body["used_by_datasets"]
    assert use["slug"] == "modbus-tcp-testbed"
    assert use["title"] == "Tráfico Modbus/TCP del banco de pruebas OT"
    assert {v["conforms_to"] for v in use["versions"]} == {f"{ONTO}/1.2.0"}

    subjects = {s["uri"]: s for s in body["subjects"]}
    assert len(subjects) == 11
    modbus = subjects[f"{OT}/modbus-tcp"]
    assert modbus["type"] == "concept"
    assert modbus["label"] == "Modbus/TCP"
    assert modbus["scheme"] == {"uri": OT, "slug": "ot", "corp": False, "label": OT_TITLE}
    assert {s["type"] for s in subjects.values()} == {"concept"}


def test_ontology_older_version(api: TestClient) -> None:
    body = api.get("/ontologies/itot", params={"version": "1.1.0"}).json()
    assert body["versioning"]["version"] == "1.1.0"
    assert body["versioning"]["current_version"] == "1.2.0"
    assert body["versioning"]["prior_version"]["version"] == "1.0.0"
    assert body["metrics"] is None and body["consistency"] is None
    assert len(body["imports"]) == 2
    assert body["alignments"] == []
    assert body["subjects"] == []


def test_other_ontologies(api: TestClient) -> None:
    pqcm = api.get("/ontologies/pqcm").json()
    assert pqcm["status"] == "draft"
    assert pqcm["versioning"]["history"][0]["version"] == "0.4.0"
    assert pqcm["used_by_datasets"] == []
    assert api.get("/ontologies/didx").status_code == 200


def _add_alignment(store: MemoryStore, annotated: bool) -> None:
    """Añade al grafo de itot 1.2.0 un alineamiento con D3FEND propio de las pruebas
    (semantico lo retiró de los datos: no tiene fuente en el prototipo)."""
    graph = store.get_graph(f"{ONTO}/1.2.0")
    axiom = (
        f"""[] a owl:Axiom ; owl:annotatedSource <{ONTO}#Control> ;
           owl:annotatedProperty rdfs:subClassOf ;
           owl:annotatedTarget <{D3F}#DefensiveTechnique> ;
           rdfs:comment "Alcance de prueba"@es ."""
        if annotated
        else ""
    )
    graph.parse(
        data=f"""
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <{ONTO}#Control> rdfs:subClassOf <{D3F}#DefensiveTechnique> .
        <{D3F}#DefensiveTechnique> a owl:Class .
        {axiom}
        """,
        format="turtle",
    )
    store.put_graph(f"{ONTO}/1.2.0", graph)


def test_alignments(api: TestClient, vocab_store: MemoryStore) -> None:
    _add_alignment(vocab_store, annotated=False)
    [alignment] = api.get("/ontologies/itot").json()["alignments"]
    # La declaración d3f:DefensiveTechnique a owl:Class no es un alineamiento.
    assert alignment["target_ontology"] == D3F
    assert alignment["prefix"] == "d3f"
    assert alignment["relation"] == "http://www.w3.org/2000/01/rdf-schema#subClassOf"
    assert alignment["version"] is None  # [VERSIÓN] de D3FEND: placeholder
    assert alignment["scope"] is None
    assert alignment["mappings"] == [
        {"source": f"{ONTO}#Control", "target": f"{D3F}#DefensiveTechnique"}
    ]


def test_alignment_scope_from_axiom_annotation(api: TestClient, vocab_store: MemoryStore) -> None:
    _add_alignment(vocab_store, annotated=True)
    [alignment] = api.get("/ontologies/itot").json()["alignments"]
    assert alignment["scope"] == "Alcance de prueba"


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/ontologies/no-existe", 404),
        ("/ontologies/externas", 404),
        ("/ontologies/itot?version=9.9.9", 404),
        ("/ontologies/Mayus", 422),
        ("/ontologies/itot?version=1.0", 422),
        ("/ontologies/itot/rdf?version=9.9.9", 404),
        ("/ontologies/itot/rdf?format=n3", 422),
    ],
)
def test_ontology_errors(api: TestClient, path: str, status: int) -> None:
    assert api.get(path).status_code == status


@pytest.mark.parametrize(
    ("params", "headers", "media"),
    [
        ({"format": "turtle"}, {}, "text/turtle"),
        ({"format": "rdfxml"}, {}, "application/rdf+xml"),
        ({"format": "jsonld"}, {}, "application/ld+json"),
        ({}, {"Accept": "application/rdf+xml"}, "application/rdf+xml"),
        ({}, {}, "text/turtle"),
    ],
)
def test_ontology_rdf_formats(
    api: TestClient, params: dict[str, str], headers: dict[str, str], media: str
) -> None:
    response = api.get("/ontologies/itot/rdf", params=params, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media)
    fmt = {"text/turtle": "turtle", "application/rdf+xml": "xml", "application/ld+json": "json-ld"}
    graph = Graph().parse(data=response.text, format=fmt[media])
    assert (URIRef(ONTO), OWL.versionIRI, URIRef(f"{ONTO}/1.2.0")) in graph
    assert (URIRef(f"{ONTO}#Activo"), RDF.type, OWL.Class) in graph


def test_ontology_rdf_version_and_406(api: TestClient) -> None:
    old = api.get("/ontologies/itot/rdf", params={"version": "1.1.0"})
    graph = Graph().parse(data=old.text, format="turtle")
    assert (URIRef(ONTO), OWL.versionIRI, URIRef(f"{ONTO}/1.1.0")) in graph
    assert api.get("/ontologies/itot/rdf", headers={"Accept": "image/png"}).status_code == 406


# --- GET /schemes -----------------------------------------------------------------------


def _labels(nodes: list[dict]) -> list[str]:
    return [n["label"] for n in nodes]


def test_scheme_detail_and_tree(api: TestClient) -> None:
    response = api.get("/schemes/ot")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "ot"
    assert body["corp"] is False
    assert body["kind"] == "skos_domain"
    assert body["title"] == OT_TITLE
    assert body["prefix"] == "ot"
    assert body["namespace"] == f"{OT}/"
    assert body["version"] == "1.0"
    assert body["status"] == "published"
    assert body["synthetic"] is True
    assert body["domain"] == DOMINIO_OT
    assert body["responsible"] is None
    assert body["metadata"]["publisher"]["label"] == "Eurecat · Unidad IT&OT Security"
    assert body["concept_count"] == 16
    tree = body["tree"]
    assert _labels(tree) == ["IEC 62443", "Modelo Purdue", "Protocolos industriales"]
    assert all(n["top_concept"] for n in tree)
    protocolos = tree[2]
    assert protocolos["slug"] == "protocolos-industriales"
    assert _labels(protocolos["children"]) == [
        "DNP3",
        "IEC 61850",
        "Modbus/TCP",
        "OPC UA",
        "PROFINET",
    ]
    assert protocolos["children"][2]["top_concept"] is False
    assert len(tree[1]["children"]) == 5
    assert _labels(tree[0]["children"]) == ["Conducto", "Nivel de seguridad (SL)", "Zona"]


def test_corp_scheme_detail(api: TestClient) -> None:
    body = api.get("/schemes/corp/trl").json()
    assert body["kind"] == "skos_corp"
    assert body["corp"] is True
    assert body["status"] == "published"
    assert body["domain"] is None
    assert body["responsible"] is None  # [RESPONSABLE]: placeholder (decisión abierta 11)
    assert body["concept_count"] == 9
    assert [n["slug"] for n in body["tree"]] == [f"trl-{i}" for i in range(1, 10)]
    assert api.get("/schemes/corp/sectores").json()["status"] == "draft"


def test_pqc_domain_has_two_schemes(api: TestClient) -> None:
    for slug in ("pqc", "did"):
        body = api.get(f"/schemes/{slug}").json()
        assert body["domain"]["slug"] == "pqc"
        assert body["domain"]["label"] == "PQC e identidad"


def test_auxiliary_schemes_are_readable(api: TestClient) -> None:
    body = api.get("/schemes/dominio").json()
    assert body["concept_count"] == 4
    assert body["domain"] is None
    assert api.get("/schemes/tipo-dataset/concepts/sintetico").json()["pref_label"] == (
        "Dataset sintético"
    )


def test_tree_survives_cycles(api: TestClient, vocab_store: MemoryStore) -> None:
    graph = Graph().parse(
        data="""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        <vocab/ciclo> a skos:ConceptScheme .
        <vocab/ciclo/a> a skos:Concept ; skos:inScheme <vocab/ciclo> ;
            skos:topConceptOf <vocab/ciclo> ; skos:broader <vocab/ciclo/b> .
        <vocab/ciclo/b> a skos:Concept ; skos:inScheme <vocab/ciclo> ;
            skos:broader <vocab/ciclo/a> .
        <vocab/ciclo/c> a skos:Concept ; skos:inScheme <vocab/ciclo> ;
            skos:broader <vocab/ciclo/c> .
        """,
        format="turtle",
        publicID=BASE_URI,
    )
    vocab_store.put_graph(f"{BASE_URI}vocab/ciclo", graph)
    body = api.get("/schemes/ciclo").json()
    assert body["concept_count"] == 3
    a = next(n for n in body["tree"] if n["slug"] == "a")
    assert [c["slug"] for c in a["children"]] == ["b"]
    assert a["children"][0]["children"] == []  # no vuelve a «a»


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/schemes/no-existe", 404),
        ("/schemes/corp", 404),
        ("/schemes/corp/no-existe", 404),
        ("/schemes/corp/ot", 404),
        ("/schemes/trl", 404),
        ("/schemes/ot/concepts/no-existe", 404),
        ("/schemes/ot/concepts/Mayus", 422),
        ("/schemes/corp/trl/concepts/modbus-tcp", 404),
        ("/schemes/Mayus", 422),
    ],
)
def test_scheme_errors(api: TestClient, path: str, status: int) -> None:
    assert api.get(path).status_code == status


def test_legacy_vocab_graph_is_not_a_scheme(api: TestClient, vocab_store: MemoryStore) -> None:
    """El grafo ``{BASE_URI}vocab/`` de la fase 2 no es el de ningún esquema."""
    legacy = Graph().parse(
        data="""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        @prefix dct: <http://purl.org/dc/terms/> .
        <vocab/legado> a skos:ConceptScheme ; dct:subject <vocab/dominio/it> .
        """,
        format="turtle",
        publicID=BASE_URI,
    )
    vocab_store.put_graph(f"{BASE_URI}vocab/", legacy)
    assert api.get("/vocabularies").json()["counts"]["skos_domain"] == 5
    assert api.get("/schemes/legado").status_code == 404


# --- GET /schemes/{slug}/concepts/{concepto} ----------------------------------------------


def test_concept_detail(api: TestClient) -> None:
    response = api.get("/schemes/ot/concepts/modbus-tcp")
    assert response.status_code == 200
    body = response.json()
    assert body["uri"] == f"{OT}/modbus-tcp"
    assert body["slug"] == "modbus-tcp"
    assert body["scheme"] == {"uri": OT, "slug": "ot", "corp": False, "label": OT_TITLE}
    assert body["pref_label"] == "Modbus/TCP"
    assert body["pref_labels"] == [
        {"value": "Modbus TCP", "lang": "en"},
        {"value": "Modbus/TCP", "lang": "es"},
    ]
    assert body["alt_labels"] == [{"value": "Modbus TCP/IP", "lang": "es"}]
    assert body["definition"].startswith("Variante de Modbus")
    assert body["top_concept"] is False
    assert body["broader"] == [
        {"uri": f"{OT}/protocolos-industriales", "label": "Protocolos industriales", "scheme": OT}
    ]
    assert body["narrower"] == []
    assert [r["uri"] for r in body["related"]] == [f"{OT}/purdue-nivel-1", f"{OT}/purdue-nivel-2"]
    assert body["related"][0]["label"] == "Nivel 1 · Control básico"
    assert body["exact_match"] == [] and body["close_match"] == []  # [QID]: placeholder
    [dataset] = body["used_by"]["datasets"]
    assert dataset["slug"] == "modbus-tcp-testbed"
    assert [v["version"] for v in dataset["versions"]] == ["2.1.0"]
    assert all(v["conforms_to"] is None for v in dataset["versions"])
    assert body["used_by"]["ontologies"] == [
        {
            "slug": "itot",
            "uri": ONTO,
            "title": "Ontología de activos y amenazas IT/OT",
            "versions": ["1.2.0"],
        }
    ]


def test_concept_narrower_and_related_inverse(api: TestClient) -> None:
    body = api.get("/schemes/ot/concepts/protocolos-industriales").json()
    assert len(body["narrower"]) == 5
    assert body["top_concept"] is True
    assert body["used_by"] == {"datasets": [], "ontologies": []}
    # profinet declara related hacia nivel-0; nivel-0 hacia profinet: un solo enlace.
    nivel0 = api.get("/schemes/ot/concepts/purdue-nivel-0").json()
    assert [r["uri"] for r in nivel0["related"]] == [f"{OT}/profinet"]
    # iec-61850 no lo usa itot (no está en su dct:subject).
    assert api.get("/schemes/ot/concepts/iec-61850").json()["used_by"]["ontologies"] == []


def test_concept_in_corp_scheme(api: TestClient) -> None:
    body = api.get("/schemes/corp/trl/concepts/trl-1").json()
    assert body["scheme"]["corp"] is True
    assert body["pref_label"] == "TRL 1"
    assert body["used_by"] == {"datasets": [], "ontologies": []}


def test_scheme_rdf(api: TestClient) -> None:
    response = api.get("/schemes/ot/rdf", params={"format": "jsonld"})
    assert response.headers["content-type"].startswith("application/ld+json")
    graph = Graph().parse(data=response.text, format="json-ld")
    assert (URIRef(f"{OT}/modbus-tcp"), SKOS.prefLabel, Literal("Modbus/TCP", lang="es")) in graph
    corp = api.get("/schemes/corp/trl/rdf")
    assert corp.headers["content-type"].startswith("text/turtle")
    assert api.get("/schemes/no-existe/rdf").status_code == 404


# --- Dominio de los datasets (fase 3) -----------------------------------------------------


def test_dataset_domain_comes_from_scheme_subject(api: TestClient) -> None:
    card = next(
        c for c in api.get("/datasets").json()["items"] if c["slug"] == "modbus-tcp-testbed"
    )
    assert card["domain"] == DOMINIO_OT
    assert card["themes"][0] == {"uri": f"{OT}/modbus-tcp", "label": "Modbus/TCP", "scheme": OT}
    detail = api.get("/datasets/modbus-tcp-testbed").json()
    assert detail["domain"] == card["domain"]
    domains = {c["slug"]: c["domain"]["slug"] for c in api.get("/datasets").json()["items"]}
    assert domains == {
        "modbus-tcp-testbed": "ot",
        "hallazgos-auditorias-intrusion": "it",
        "ejemplos-adversarios-vision": "ia",
    }


def _publish_variant(store: MemoryStore, uris: Uris, themes: str, slug: str) -> None:
    from app.config import get_settings

    text = (FIXTURE_DATA_DIR / "sintetico" / "hallazgos-auditorias-intrusion.ttl").read_text()
    text = text.replace("it:cwe , it:control-iso-27001", themes)
    text = text.replace("hallazgos-auditorias-intrusion", slug)
    graph = Graph().parse(data=text, format="turtle", publicID=BASE_URI)
    ingest.publish(store, ingest.prepare_series(graph, uris, get_settings().semantic_dir))


def test_did_scheme_maps_to_pqc_domain(
    api: TestClient, vocab_store: MemoryStore, uris: Uris
) -> None:
    concept = f"<{BASE_URI}vocab/did/credencial-verificable>"
    _publish_variant(vocab_store, uris, concept, "identidad-prueba")
    cards = api.get("/datasets", params={"domain": "pqc"}).json()["items"]
    assert [c["slug"] for c in cards] == ["identidad-prueba"]
    assert cards[0]["domain"] == {
        "slug": "pqc",
        "uri": f"{BASE_URI}vocab/dominio/pqc",
        "label": "PQC e identidad",
    }
    assert cards[0]["themes"][0]["label"] == "Credencial verificable"


def test_scheme_without_subject_falls_back_to_scheme_uri(
    api: TestClient, vocab_store: MemoryStore
) -> None:
    graph = vocab_store.get_graph(OT)
    graph.remove((URIRef(OT), DCT.subject, None))
    vocab_store.put_graph(OT, graph)
    detail = api.get("/datasets/modbus-tcp-testbed").json()
    assert detail["domain"] == {**DOMINIO_OT, "label": OT_TITLE}


def test_labels_only_from_the_concepts_own_scheme_graph(
    api: TestClient, vocab_store: MemoryStore
) -> None:
    """Un grafo que no es el del esquema del concepto no aporta etiquetas ni dominio."""
    fake = Graph().parse(
        data=f"""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        @prefix dct: <http://purl.org/dc/terms/> .
        <{OT}/modbus-tcp> skos:prefLabel "FALSO"@es ; skos:inScheme <{BASE_URI}vocab/corp/x> .
        <{BASE_URI}vocab/corp/x> a skos:ConceptScheme ; dct:subject <{BASE_URI}vocab/dominio/ia> .
        <{BASE_URI}vocab/dominio/ot> skos:prefLabel "FALSO"@es .
        """,
        format="turtle",
    )
    for graph_name in (
        f"{BASE_URI}vocab/corp/x",
        f"{BASE_URI}otro",
        "http://otro.example/g",
        f"{BASE_URI}vocab/",
    ):
        vocab_store.put_graph(graph_name, fake)
    detail = api.get("/datasets/modbus-tcp-testbed").json()
    assert detail["domains"] == [DOMINIO_OT]
    labels = {t["label"] for t in detail["version"]["metadata"]["themes"]}
    assert "FALSO" not in labels
    concept = api.get("/schemes/ot/concepts/modbus-tcp").json()
    assert concept["pref_label"] == "Modbus/TCP"
    assert "FALSO" not in json.dumps(api.get("/datasets").json())
    assert "FALSO" not in json.dumps(api.get("/schemes/ot").json())


# --- Dominio en las tarjetas, altLabel en el árbol y descarga del RDF -------------------


def test_vocabulary_cards_have_domain(api: TestClient) -> None:
    cards = {c["uri"]: c for c in api.get("/vocabularies").json()["items"]}
    assert cards[OT]["domain"] == DOMINIO_OT
    assert cards[f"{BASE_URI}vocab/did"]["domain"]["slug"] == "pqc"
    assert cards[f"{BASE_URI}vocab/did"]["domain"]["label"] == "PQC e identidad"
    # Sin dominio en el RDF: ontologías (no se deduce de sus dct:subject) y corporativos.
    assert cards[ONTO]["domain"] is None
    assert cards["https://saref.etsi.org/core/"]["domain"] is None
    assert cards[f"{BASE_URI}vocab/corp/trl"]["domain"] is None


@pytest.mark.parametrize(
    ("domain", "slugs"),
    [("pqc", {"pqc", "did"}), ("ot", {"ot"}), ("it", {"it"}), ("ia", {"ia"})],
)
def test_vocabularies_filter_domain(api: TestClient, domain: str, slugs: set[str]) -> None:
    body = api.get("/vocabularies", params={"domain": domain}).json()
    assert {c["slug"] for c in body["items"]} == slugs
    assert {c["domain"]["slug"] for c in body["items"]} == {domain}
    assert body["total"] == len(slugs)
    assert body["counts"] == {"own": 3, "external": 3, "skos_corp": 4, "skos_domain": 5}


def test_vocabularies_filter_domain_combined_and_invalid(api: TestClient) -> None:
    assert api.get("/vocabularies", params={"domain": "ot", "kind": "own"}).json()["items"] == []
    assert api.get("/vocabularies", params={"domain": "ot", "q": "nada"}).json()["total"] == 0
    assert api.get("/vocabularies", params={"domain": "otro"}).status_code == 422


def test_tree_nodes_have_alt_labels(api: TestClient) -> None:
    tree = api.get("/schemes/ot").json()["tree"]
    protocolos = next(n for n in tree if n["slug"] == "protocolos-industriales")
    modbus = next(n for n in protocolos["children"] if n["slug"] == "modbus-tcp")
    assert modbus["alt_labels"] == [{"value": "Modbus TCP/IP", "lang": "es"}]
    assert protocolos["alt_labels"] == []


@pytest.mark.parametrize(
    ("path", "params", "name"),
    [
        ("/ontologies/itot/rdf", {"download": "true"}, "itot-1.2.0.ttl"),
        (
            "/ontologies/itot/rdf",
            {"download": "1", "version": "1.1.0", "format": "rdfxml"},
            "itot-1.1.0.rdf",
        ),
        ("/schemes/ot/rdf", {"download": "1"}, "ot-1.0.ttl"),
        ("/schemes/corp/trl/rdf", {"download": "1", "format": "jsonld"}, "corp-trl-1.0.jsonld"),
        ("/datasets/modbus-tcp-testbed/rdf", {"download": "1"}, "modbus-tcp-testbed-2.1.0.ttl"),
        (
            "/datasets/modbus-tcp-testbed/rdf",
            {"download": "1", "version": "1.0.0", "format": "jsonld"},
            "modbus-tcp-testbed-1.0.0.jsonld",
        ),
    ],
)
def test_rdf_download_sets_attachment(
    api: TestClient, path: str, params: dict[str, str], name: str
) -> None:
    response = api.get(path, params=params)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="{name}"'


@pytest.mark.parametrize(
    "path", ["/ontologies/itot/rdf", "/schemes/ot/rdf", "/datasets/modbus-tcp-testbed/rdf"]
)
def test_rdf_inline_by_default(api: TestClient, path: str) -> None:
    for params in ({}, {"download": "false"}):
        response = api.get(path, params=params)
        assert response.status_code == 200
        assert "content-disposition" not in response.headers
    assert api.get(path, params={"download": "quizas"}).status_code == 422


def test_download_filename_drops_unsafe_parts() -> None:
    from app import downloads

    assert downloads.filename(["itot", '1.0"; x=y'], "text/turtle") == "itot.ttl"
    assert downloads.filename(["../etc", None], "application/rdf+xml") == "rdf.rdf"
