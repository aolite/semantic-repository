"""Correcciones de la revisión de qa de G3 (QA-G3-01 a 07 y 10, y el tipo ``auxiliary``).

Cada bloque lleva el identificador del hallazgo. Las pruebas de Pellet necesitan Java 25.
"""

import json
import multiprocessing
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import cli as cli_module
from app import ingest, owl_metrics, shacl_worker, vocab_ingest
from app.config import get_settings
from app.models import AuditEvent, OntologyMetricsRecord, Role, User
from app.triplestore import MemoryStore
from app.uris import Uris
from tests.conftest import BASE_URI
from tests.test_vocab_ingest import _onto, _scheme

TTL = {"Content-Type": "text/turtle"}
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
PRUEBA = f"{BASE_URI}onto/prueba"

requires_java = pytest.mark.skipif(
    not owl_metrics.java_available(), reason="Pellet necesita Java 25 o superior"
)


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]) -> dict[str, str]:
    make_user("editora", Role.EDITOR)
    return login("editora")


@pytest.fixture
def quiet(client: TestClient) -> TestClient:
    return TestClient(client.app, raise_server_exceptions=False)


@pytest.fixture
def no_pellet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        owl_metrics,
        "check_consistency",
        lambda *_a, **_k: owl_metrics.Consistency(detail="razonador desactivado"),
    )


def _nothing_written(store: MemoryStore, session_factory: sessionmaker[Session]) -> None:
    assert store.graph_names() == set()
    with session_factory() as session:
        assert session.scalars(select(AuditEvent)).first() is None or all(
            e.action.startswith(("login", "user")) for e in session.scalars(select(AuditEvent))
        )
        assert session.scalars(select(OntologyMetricsRecord)).first() is None


def _chain(depth: int, slug: str = "prueba") -> bytes:
    """Esquema con una cadena skos:broader de ``depth`` conceptos (``depth - 1`` niveles)."""
    lines = [
        f"<vocab/{slug}> skos:hasTopConcept <vocab/{slug}/c0> .",
        f"<vocab/{slug}/c0> a skos:Concept ; skos:inScheme <vocab/{slug}> ; "
        f'skos:topConceptOf <vocab/{slug}> ; skos:prefLabel "c0"@es .',
    ]
    lines += [
        f"<vocab/{slug}/c{i}> a skos:Concept ; skos:inScheme <vocab/{slug}> ; "
        f'skos:broader <vocab/{slug}/c{i - 1}> ; skos:prefLabel "c{i}"@es .'
        for i in range(1, depth)
    ]
    return _scheme("\n".join(lines), uri=f"vocab/{slug}")


# --- QA-G3-06: esquemas auxiliares reservados ------------------------------------------


@pytest.mark.parametrize("slug", ["dominio", "tipo-dataset"])
def test_auxiliary_schemes_cannot_be_published_by_api(
    client: TestClient, editor: dict[str, str], loaded_store: MemoryStore, slug: str
) -> None:
    before = {n: len(loaded_store.get_graph(n)) for n in loaded_store.graph_names()}
    body = _scheme(
        f"<vocab/{slug}> skos:hasTopConcept <vocab/{slug}/ot> . <vocab/{slug}/ot> a skos:Concept ; "
        f"skos:inScheme <vocab/{slug}> ; skos:topConceptOf <vocab/{slug}> ; "
        f'skos:prefLabel "X"@es .',
        uri=f"vocab/{slug}",
    )
    response = client.post("/schemes", content=body, headers=editor | TTL)
    assert response.status_code == 422
    assert response.json()["kind"] == "uri"
    assert "reservado" in response.json()["detail"]
    assert {n: len(loaded_store.get_graph(n)) for n in loaded_store.graph_names()} == before


def test_auxiliary_schemes_have_their_own_kind(
    client: TestClient, vocab_store: MemoryStore
) -> None:
    assert client.get("/schemes/dominio").json()["kind"] == "auxiliary"
    assert client.get("/schemes/tipo-dataset").json()["kind"] == "auxiliary"
    assert client.get("/schemes/ot").json()["kind"] == "skos_domain"
    assert client.get("/schemes/corp/trl").json()["kind"] == "skos_corp"


# --- QA-G3-01: lo que owlready2 no puede leer -------------------------------------------


@pytest.mark.usefixtures("no_pellet")
@pytest.mark.parametrize(
    "body",
    [
        f':p a owl:DatatypeProperty . :i a owl:NamedIndividual ; :p "abc"^^<{XSD}integer> .',
        f':A a owl:Class ; rdfs:comment "x"^^<{XSD}decimal> .',
    ],
)
def test_ill_typed_literal_is_422_and_writes_nothing(
    quiet: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    body: str,
) -> None:
    response = quiet.post("/ontologies", content=_onto(body), headers=editor | TTL)
    assert response.status_code == 422, response.text
    payload = response.json()
    assert payload["kind"] == "syntax"
    assert (payload["issues"] and payload["issues"][0]["value"].endswith(f"^^<{XSD}integer>")) or (
        payload["issues"][0]["value"].endswith(f"^^<{XSD}decimal>")
    )
    assert "owlready2" not in response.text and "Traceback" not in response.text
    _nothing_written(store, session_factory)


@pytest.mark.usefixtures("no_pellet")
def test_any_owlready2_load_failure_is_422(
    quiet: TestClient,
    editor: dict[str, str],
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import owlready2

    def boom(*_args: object, **_kwargs: object) -> None:
        raise owlready2.OwlReadyOntologyParsingError("fallo en /opt/venv/owlready2/x.py")

    monkeypatch.setattr(owlready2.World, "get_ontology", boom)
    response = quiet.post("/ontologies", content=_onto(":A a owl:Class ."), headers=editor | TTL)
    assert response.status_code == 422, response.text
    assert "/opt/venv" not in response.text
    _nothing_written(store, session_factory)


@pytest.mark.parametrize("error", [RuntimeError("en /opt/venv/x"), ValueError("ilegible")])
def test_unexpected_reasoner_exception_gives_generic_null(
    quiet: TestClient,
    editor: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    import owlready2

    def boom(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(owl_metrics, "java_available", lambda: True)
    monkeypatch.setattr(owlready2, "sync_reasoner_pellet", boom)
    response = quiet.post("/ontologies", content=_onto(":A a owl:Class ."), headers=editor | TTL)
    assert response.status_code == 201, response.text
    consistency = response.json()["consistency"]
    assert consistency["consistent"] is None
    assert consistency["detail"] == owl_metrics.REASONER_FAILED
    assert "/opt/venv" not in response.text


@pytest.mark.usefixtures("no_pellet")
def test_load_semantic_analyzes_before_writing(
    store: MemoryStore,
    session_factory: sessionmaker[Session],
    semantic_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una ontología que owlready2 no puede leer hace fallar la carga sin escribir nada."""
    broken = tmp_path / "semantic"
    import shutil

    shutil.copytree(semantic_dir, broken)
    path = broken / "ontologias" / "itot" / "1.2.0.ttl"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text + f'\n<onto/itot#Activo> <{RDF_NS}value> "abc"^^<{XSD}integer> .\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SEMANTIC_DIR", str(broken))
    get_settings.cache_clear()
    ingest.clear_caches()
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)
    try:
        result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
    finally:
        monkeypatch.setenv("SEMANTIC_DIR", str(semantic_dir))
        get_settings.cache_clear()
        ingest.clear_caches()
    assert result.exit_code == 1, result.output
    assert "1.2.0.ttl" in result.output
    assert "no se ha cargado nada" in result.output
    assert store.graph_names() == set()
    with session_factory() as session:
        assert session.scalars(select(OntologyMetricsRecord)).first() is None


# --- QA-G3-02 y QA-G3-07: detalle genérico y sin ficheros temporales ------------------------


def test_java_error_detail_is_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    import owlready2

    trace = (
        "Java error message is:\nException in thread main java.io.FileNotFoundException: "
        "/tmp/tmpabc (No such file)\n\tat pellet.Pellet.main(Pellet.java:59)"
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise owlready2.OwlReadyJavaError(trace)

    monkeypatch.setattr(owl_metrics, "java_available", lambda: True)
    monkeypatch.setattr(owlready2, "sync_reasoner_pellet", boom)
    graph = ingest.parse_rdf(_onto(":A a owl:Class ."), "turtle", BASE_URI)
    result = owl_metrics.check_consistency(graph, PRUEBA, timeout_seconds=5, java_memory_mb=256)
    assert result.consistent is None
    assert result.detail == owl_metrics.REASONER_FAILED
    for leaked in ("\tat ", ".java", "/tmp/", "Exception"):  # noqa: S108
        assert leaked not in result.detail


CYCLIC_LIST = (
    f":A a owl:Class ; owl:unionOf _:l . _:l <{RDF_NS}first> :B ; <{RDF_NS}rest> _:l . "
    ":B a owl:Class ."
)


@pytest.fixture
def private_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    yield tmp_path


@requires_java
@pytest.mark.parametrize(
    ("body", "timeout", "expected"),
    [
        (":A a owl:Class .", 60.0, True),
        (":A a owl:Class ; owl:equivalentClass owl:Nothing . :i a :A .", 60.0, False),
        (CYCLIC_LIST, 60.0, None),
        (":A a owl:Class .", 0.001, None),
    ],
    ids=["consistente", "inconsistente", "fallo", "tiempo"],
)
def test_reasoner_leaves_no_temporary_files(
    private_tmp: Path, body: str, timeout: float, expected: bool | None
) -> None:
    graph = ingest.parse_rdf(_onto(body), "turtle", BASE_URI)
    result = owl_metrics.check_consistency(
        graph, PRUEBA, timeout_seconds=timeout, java_memory_mb=512
    )
    assert result.consistent is expected
    if expected is None:
        assert "\tat " not in (result.detail or "") and ".java" not in (result.detail or "")
    assert list(private_tmp.iterdir()) == []


# --- QA-G3-04: profundidad de la jerarquía ------------------------------------------------


def test_hierarchy_deeper_than_the_limit_is_rejected(
    client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    depth = vocab_ingest.MAX_CONCEPT_DEPTH
    too_deep = client.post("/schemes", content=_chain(depth + 2), headers=editor | TTL)
    assert too_deep.status_code == 422
    assert too_deep.json()["kind"] == "limit"
    assert store.graph_names() == set()
    ok = client.post("/schemes", content=_chain(depth + 1), headers=editor | TTL)
    assert ok.status_code == 201, ok.text
    node, levels = client.get("/schemes/prueba").json()["tree"][0], 0
    while node["children"]:
        node, levels = node["children"][0], levels + 1
    assert levels == depth


def test_concept_depth_ignores_cycles() -> None:
    graph = Graph().parse(
        data="""
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        <vocab/x/a> a skos:Concept ; skos:broader <vocab/x/b> .
        <vocab/x/b> a skos:Concept ; skos:broader <vocab/x/a> .
        <vocab/x/c> a skos:Concept ; skos:broader <vocab/x/c> ; skos:narrower <vocab/x/d> .
        <vocab/x/d> a skos:Concept .
        """,
        format="turtle",
        publicID=BASE_URI,
    )
    assert vocab_ingest.concept_depth(graph, URIRef(f"{BASE_URI}vocab/x")) == 1


def test_tree_of_stored_deep_hierarchy_is_built_without_recursion(
    client: TestClient, store: MemoryStore
) -> None:
    """Datos guardados antes del límite (1500 niveles): el árbol se corta, sin 500."""
    graph = Graph().parse(data=_chain(1500, "honda"), format="turtle", publicID=BASE_URI)
    store.put_graph(f"{BASE_URI}vocab/honda", graph)
    response = client.get("/schemes/honda")
    assert response.status_code == 200
    node, levels = response.json()["tree"][0], 0
    while node["children"]:
        node, levels = node["children"][0], levels + 1
    assert levels == vocab_ingest.MAX_CONCEPT_DEPTH
    assert client.get("/schemes/honda/concepts/c1499").status_code == 200


# --- QA-G3-05: RDF/XML no representable ---------------------------------------------------


@pytest.mark.usefixtures("no_pellet")
@pytest.mark.parametrize("predicate", ["http://x.example/p/1", "urn:x:1"])
def test_unrepresentable_rdfxml_is_406_not_500(
    quiet: TestClient, editor: dict[str, str], predicate: str
) -> None:
    body = _onto(f':A a owl:Class ; <{predicate}> "v" .')
    assert quiet.post("/ontologies", content=body, headers=editor | TTL).status_code == 201
    assert quiet.get("/ontologies/prueba/rdf", params={"format": "rdfxml"}).status_code == 406
    accept = {"Accept": "application/rdf+xml"}
    assert quiet.get("/onto/prueba", headers=accept).status_code == 406
    assert quiet.get("/ontologies/prueba/rdf", params={"format": "turtle"}).status_code == 200


# --- QA-G3-03: bomba de expansión y límite de tripletas ------------------------------------


LONG_PREFIX = "http://x.example/" + "a" * 100_000 + "/"


@pytest.mark.parametrize(
    ("data", "rdf_format"),
    [
        (
            (
                f"@prefix p: <{LONG_PREFIX}> .\n"
                + "\n".join(f"p:s{i} p:p p:o{i} ." for i in range(200))
            ).encode(),
            "turtle",
        ),
        (
            json.dumps(
                {
                    "@context": {"p": LONG_PREFIX},
                    "@graph": [{"@id": f"p:s{i}", "p:p": {"@id": f"p:o{i}"}} for i in range(200)],
                }
            ).encode(),
            "json-ld",
        ),
    ],
)
def test_prefix_bomb_is_aborted(data: bytes, rdf_format: ingest.RdfFormat) -> None:
    with pytest.raises(ingest.IngestError) as error:
        ingest.parse_rdf(data, rdf_format, BASE_URI)
    assert error.value.kind == "limit"
    assert "IRI" in error.value.detail


def test_expansion_ratio_is_bounded() -> None:
    """IRIs por debajo del máximo, pero el grafo expandido crece más de 32 veces."""
    prefix = "http://x.example/" + "b" * 3000 + "/"
    data = (
        f"@prefix p: <{prefix}> .\n" + "\n".join(f"p:{i} p:p p:{i} ." for i in range(3000))
    ).encode()
    with pytest.raises(ingest.IngestError) as error:
        ingest.parse_rdf(data, "turtle", BASE_URI)
    assert error.value.kind == "limit"
    assert "expandido" in error.value.detail


def test_triple_limit() -> None:
    data = "\n".join(f"<urn:x:s{i}> <urn:x:p> <urn:x:o> ." for i in range(11)).encode()
    with pytest.raises(ingest.IngestError) as error:
        ingest.parse_rdf(data, "turtle", BASE_URI, max_triples=10)
    assert error.value.kind == "limit"
    assert len(ingest.parse_rdf(data, "turtle", BASE_URI, max_triples=11)) == 11


@pytest.fixture
def small_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``INGEST_MAX_TRIPLES`` bajo. Debe pedirse antes que ``client``."""
    monkeypatch.setenv("INGEST_MAX_TRIPLES", "20")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("INGEST_MAX_TRIPLES")
    get_settings.cache_clear()


@pytest.mark.parametrize("path", ["/datasets", "/schemes", "/ontologies"])
def test_triple_limit_applies_to_every_ingest(
    small_limits: None, client: TestClient, editor: dict[str, str], store: MemoryStore, path: str
) -> None:
    body = "\n".join(f"<vocab/prueba/c{i}> <urn:x:p> <urn:x:o> ." for i in range(30)).encode()
    response = client.post(path, content=body, headers=editor | TTL)
    assert response.status_code == 422
    assert response.json()["kind"] == "limit"
    assert store.graph_names() == set()


# --- QA-G3-10: SHACL con tiempo y memoria limitados ----------------------------------------


@pytest.fixture
def tiny_shacl_timeout(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SHACL_TIMEOUT_SECONDS", "0.001")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("SHACL_TIMEOUT_SECONDS")
    get_settings.cache_clear()


def test_shacl_timeout_kills_the_worker(
    tiny_shacl_timeout: None, client: TestClient, editor: dict[str, str], store: MemoryStore
) -> None:
    response = client.post("/schemes", content=_chain(3), headers=editor | TTL)
    assert response.status_code == 422
    body = response.json()
    assert body["kind"] == "limit"
    assert "tiempo" in body["detail"] and "SHACL_TIMEOUT_SECONDS" in body["detail"]
    assert store.graph_names() == set()
    assert [p for p in multiprocessing.active_children() if p.is_alive()] == []


def test_shacl_out_of_memory_is_422(
    client: TestClient, editor: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_memory(*_args: object, **_kwargs: object) -> None:
        raise shacl_worker.ShaclLimitError("memory")

    monkeypatch.setattr(shacl_worker, "validate", no_memory)
    response = client.post("/schemes", content=_chain(3), headers=editor | TTL)
    assert response.status_code == 422
    assert response.json()["kind"] == "limit"
    assert "memoria" in response.json()["detail"]


def test_shacl_worker_still_reports_violations(semantic_dir: Path) -> None:
    """La validación en el proceso hijo devuelve el mismo informe que antes."""
    graph = ingest.parse_rdf(_scheme("", description=False), "turtle", BASE_URI)
    with pytest.raises(ingest.IngestError) as error:
        vocab_ingest.prepare_scheme(graph, Uris(BASE_URI), get_settings())
    assert error.value.kind == "shacl"
    assert error.value.issues
    assert error.value.report
