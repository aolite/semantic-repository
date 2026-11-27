"""Decisión 51: las ontologías externas se sustituyen enteras y cada sustitución genera una
versión nueva ``{BASE_URI}onto/externas/{slug}/{n}``.

Contrato: ``semantic/uris.md``, «Versiones de las ontologías externas», y las formas
``itsh:ExternalVersionShape`` e ``itsh:ExternalOntologyVersionedShape``. Cubre la primera y
la segunda sustitución, la inmutabilidad, la concurrencia, cada error, los roles,
``load-semantic``, las métricas, la resolución de URIs y SPARQL.

Salvo en las pruebas de métricas, el cálculo de métricas de la externa se sustituye por uno
sin Pellet (``fake_metrics``) para no lanzar Java en cada sustitución.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import bajas, external_versions, ingest, owl_metrics, vocab_ingest
from app import cli as cli_module
from app.config import Settings, get_settings
from app.db import Base
from app.models import (
    AuditAction,
    AuditEvent,
    ExternalVersionPrefix,
    OntologyMetricsRecord,
    Role,
    User,
    WithdrawnPrefix,
)
from app.storage import DiskStorage
from app.triplestore import MemoryStore, TriplestoreError
from app.uris import ADMS, DCAT, DCT, FOAF, PROV, VANN, Uris
from tests.conftest import BASE_URI

SAREF = "https://saref.etsi.org/core/"
SOSA = "http://www.w3.org/ns/sosa/"
EXTERNAS = f"{BASE_URI}onto/externas"
V1 = f"{EXTERNAS}/saref/1"
V2 = f"{EXTERNAS}/saref/2"
V3 = f"{EXTERNAS}/saref/3"
TURTLE = {"Accept": "text/turtle"}


def official(iri: str = SAREF, extra: str = "") -> bytes:
    """Fichero «oficial» mínimo: lleva su propio owl:versionIRI y títulos en inglés, como
    los reales, una clase de su espacio de nombres y otra ajena (que no cuenta)."""
    return f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dct: <http://purl.org/dc/terms/> .
<{iri}> a owl:Ontology ; owl:versionIRI <{iri}v9.9.9/> ;
    dct:title "Official title"@en ; owl:imports <http://www.w3.org/ns/sosa/> .
<{iri}Device> a owl:Class ; rdfs:comment "A device"@en .
<{iri}Sensor> a owl:Class ; rdfs:subClassOf <{iri}Device> .
<http://otra.example.org/Ajena> a owl:Class .
{extra}
""".encode()


def form(**overrides: str | None) -> dict[str, str]:
    data: dict[str, str | None] = {
        "title": "SAREF · Smart Applications REFerence ontology",
        "description": "Ontología de referencia de ETSI.",
        "version_info": "3.2.1",
        "prefix": "saref",
        "namespace": SAREF,
        "publisher": "ETSI",
        "version_notes": "Sustitución de prueba.",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def post(
    api: TestClient,
    headers: dict[str, str] | None,
    slug: str = "saref",
    body: bytes | None = None,
    media: str = "text/turtle",
    filename: str = "ontologia.ttl",
    **fields: str | None,
):
    return api.post(
        f"/ontologies/externas/{slug}/versions",
        data=form(**fields),
        files={"file": (filename, official() if body is None else body, media)},
        headers=headers or {},
    )


@pytest.fixture
def fake_metrics(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Métricas reales de owlready2, sin Pellet. Registra el espacio de nombres usado."""
    namespaces: list[str] = []

    def fake(graph: Graph, ontology_iri: str, namespace: str, _settings: object):
        namespaces.append(namespace)
        metrics = owl_metrics.compute_metrics(graph, ontology_iri, namespace)
        return metrics.to_dict(), owl_metrics.Consistency(detail="prueba").to_dict()

    monkeypatch.setattr(external_versions, "compute_external_metrics", fake)
    return namespaces


@pytest.fixture
def api(client: TestClient, vocab_store: MemoryStore, fake_metrics: list[str]) -> TestClient:
    return client


@pytest.fixture
def editor(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("editora", Role.EDITOR)
    return login("editora")


def reference(store: MemoryStore, iri: str = SAREF) -> Graph:
    return bajas.subject_description(store.get_graph(EXTERNAS), URIRef(iri))


# --- Primera y segunda sustitución ------------------------------------------------------


def test_first_and_second_substitution(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    session_factory: sessionmaker[Session],
    fake_metrics: list[str],
) -> None:
    sosa_before = reference(vocab_store, SOSA)
    first = post(api, editor)
    assert first.status_code == 201, first.text
    body = first.json()
    assert (body["slug"], body["uri"], body["number"], body["version"]) == ("saref", SAREF, 1, "1")
    assert (body["version_uri"], body["graph"], body["previous_version"]) == (V1, V1, None)
    assert body["metrics"]["classes"] == 2  # solo las del espacio de nombres de la referencia
    assert body["metrics"]["imports"] == 1
    assert fake_metrics == [SAREF]

    v1 = vocab_store.get_graph(V1)
    node = URIRef(V1)
    # El grafo de la versión: el fichero oficial completo y el registro de la versión.
    assert (URIRef(SAREF), OWL.versionIRI, URIRef(f"{SAREF}v9.9.9/")) in v1
    assert (node, RDF.type, PROV.Entity) in v1
    assert (node, DCT.isVersionOf, URIRef(SAREF)) in v1
    assert (node, DCAT.version, Literal("1")) in v1
    assert (node, OWL.versionInfo, Literal("3.2.1")) in v1
    assert (node, PROV.generatedAtTime, None) in v1
    assert (node, DCAT.previousVersion, None) not in v1
    assert (node, ADMS.versionNotes, Literal("Sustitución de prueba.", lang="es")) in v1

    ref = reference(vocab_store)
    assert set(ref.objects(URIRef(SAREF), DCAT.hasVersion)) == {node}
    assert ref.value(URIRef(SAREF), DCAT.hasCurrentVersion) == node
    assert ref.value(URIRef(SAREF), OWL.versionIRI) is None
    publisher = ref.value(URIRef(SAREF), DCT.publisher)
    assert ref.value(publisher, FOAF.name) == Literal("ETSI")

    second = post(api, editor, version_info="4.1.1", version_notes="Segunda.", publisher=None)
    assert second.status_code == 201, second.text
    assert (second.json()["number"], second.json()["previous_version"]) == (2, V1)
    v2 = vocab_store.get_graph(V2)
    assert (URIRef(V2), DCAT.previousVersion, node) in v2
    assert (URIRef(V2), PROV.wasRevisionOf, node) in v2
    # La versión 1 es inmutable.
    assert isomorphic(vocab_store.get_graph(V1), v1)
    ref = reference(vocab_store)
    assert set(ref.objects(URIRef(SAREF), DCAT.hasVersion)) == {node, URIRef(V2)}
    assert ref.value(URIRef(SAREF), DCAT.hasCurrentVersion) == URIRef(V2)
    assert ref.value(URIRef(SAREF), OWL.versionInfo) == Literal("4.1.1")
    assert ref.value(URIRef(SAREF), DCT.publisher) is None  # el publicador antiguo se va
    # Solo se reescribe el registro de esa externa.
    assert isomorphic(reference(vocab_store, SOSA), sosa_before)
    # Los registros guardados cumplen las formas, también la referencia con las dos.
    ingest.validate_shacl(
        ref + bajas.subject_description(v2, URIRef(V2)),
        get_settings().semantic_dir,
        BASE_URI,
        support=False,
    )

    with session_factory() as session:
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == AuditAction.EXTERNAL_ONTOLOGY_REPLACED.value
                )
            )
        )
        prefixes = {r.version_uri: r.prefix for r in session.scalars(select(ExternalVersionPrefix))}
    assert [e.details["version_uri"] for e in events] == [V1, V2]
    assert {e.actor_username for e in events} == {"editora"}
    assert prefixes == {V1: "saref", V2: "saref"}


def test_detail_cards_and_own_ontologies(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    before = api.get("/ontologies/externas/saref").json()
    assert (before["slug"], before["kind"], before["status"]) == ("saref", "external", "referenced")
    assert before["versions"] == [] and before["current_version"] is None
    assert (before["prefix"], before["version"], before["publisher"]) == ("saref", "3.2.1", "ETSI")

    assert post(api, editor, version_info="[VERSIÓN]").status_code == 201
    assert post(api, editor, version_info="4.0.0").status_code == 201
    detail = api.get("/ontologies/externas/saref").json()
    assert [v["number"] for v in detail["versions"]] == [2, 1]
    assert detail["current_version"]["uri"] == V2
    assert detail["current_version"]["metrics"]["classes"] == 2
    assert detail["current_version"]["consistency"]["reasoner"] == "Pellet"
    assert detail["versions"][1]["version_info"] is None  # placeholder: se omite
    assert detail["versions"][1]["current"] is False
    assert detail["versions"][0]["previous_version"] == V1
    assert detail["versions"][0]["notes"] == "Sustitución de prueba."
    assert detail["title"] == "SAREF · Smart Applications REFerence ontology"

    page = api.get("/vocabularies").json()
    cards = {c["uri"]: c for c in page["items"]}
    assert cards[SAREF]["slug"] == "saref"
    assert cards[SAREF]["version"] == "4.0.0"
    assert cards[SAREF]["metrics"] == {"classes": 2, "properties": 0}
    assert cards[SOSA]["slug"] == "sosa" and cards[SOSA]["metrics"] is None
    # El owl:versionIRI del fichero oficial no crea ninguna ontología propia.
    assert page["counts"]["own"] == 3 and page["counts"]["external"] == 3
    assert api.get("/ontologies/externas/nada").status_code == 404


# --- Errores ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "fields", "kind"),
    [
        (b"@prefix : <x> . esto no es turtle", {}, "syntax"),
        (official("https://otra.example.org/onto/"), {}, "structure"),
        (official(extra=f"<{BASE_URI}onto/itot#X> a <{SAREF}Device> ."), {}, "uri"),
        (None, {"prefix": "Saref"}, "structure"),
        (None, {"title": None}, "structure"),
        (None, {"namespace": "no es una iri"}, "structure"),
    ],
)
def test_unprocessable(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    body: bytes | None,
    fields: dict[str, str | None],
    kind: str,
) -> None:
    before = vocab_store.get_graph(EXTERNAS)
    response = post(api, editor, body=body, **fields)
    assert response.status_code == 422, response.text
    assert response.json()["kind"] == kind
    assert V1 not in vocab_store.graph_names()
    assert isomorphic(vocab_store.get_graph(EXTERNAS), before)


def test_shacl_of_the_records(
    api: TestClient, editor: dict[str, str], uris: Uris, settings: Settings
) -> None:
    info = external_versions.ExternalInfo(SAREF, "saref", "saref", {}, None)
    upload = external_versions.ExternalUpload(b"", "turtle", "SAREF", "saref", SAREF)
    ref, record = external_versions.build_records(
        uris, info, "saref", upload, 1, external_versions.datetime.now(external_versions.UTC)
    )
    external_versions.validate_records(ref, record, uris, settings)
    record.remove((URIRef(V1), PROV.generatedAtTime, None))
    with pytest.raises(ingest.IngestError) as raised:
        external_versions.validate_records(ref, record, uris, settings)
    assert raised.value.kind == "shacl"
    # Y la API lo devuelve como 422 shacl.
    ref.add((URIRef(SAREF), DCAT.hasCurrentVersion, URIRef(V2)))  # dos actuales
    original = external_versions.build_records
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(external_versions, "build_records", lambda *_a: (ref, record))
        response = post(api, editor)
    assert external_versions.build_records is original
    assert response.status_code == 422 and response.json()["kind"] == "shacl"


def test_not_found_and_formats(api: TestClient, editor: dict[str, str]) -> None:
    assert post(api, editor, slug="nada").status_code == 404
    jsonld = Graph().parse(data=official().decode(), format="turtle").serialize(format="json-ld")
    response = post(
        api, editor, body=jsonld.encode(), media="application/octet-stream", filename="s.jsonld"
    )
    assert response.status_code == 201, response.text
    assert post(api, editor, media="text/plain", filename="s.txt").status_code == 415
    no_file = api.post("/ontologies/externas/saref/versions", data=form(), headers=editor)
    assert no_file.status_code in (400, 415)


def test_prefix_conflicts_and_reservations(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str], db: Session
) -> None:
    # De otra externa o de una ontología propia viva: 409 prefix_in_use.
    for prefix in ("sosa", "itot"):
        response = post(api, editor, prefix=prefix)
        assert response.status_code == 409, response.text
        assert response.json()["kind"] == "prefix_in_use"
    # De un recurso dado de baja: 409 prefix_withdrawn.
    db.add(WithdrawnPrefix(prefix="viejo", resource_uri=f"{BASE_URI}onto/viejo"))
    db.commit()
    response = post(api, editor, prefix="viejo")
    assert (response.status_code, response.json()["kind"]) == (409, "prefix_withdrawn")
    assert V1 not in vocab_store.graph_names()

    # El suyo vale; el que deja de usar queda reservado para ella.
    assert post(api, editor).status_code == 201
    assert post(api, editor, prefix="sarefcore").status_code == 201
    assert reference(vocab_store).value(URIRef(SAREF), VANN.preferredNamespacePrefix) == Literal(
        "sarefcore"
    )
    # El slug no cambia aunque cambie el prefijo.
    assert api.get("/ontologies/externas/saref").json()["prefix"] == "sarefcore"
    sosa = post(api, editor, slug="sosa", body=official(SOSA), prefix="saref", namespace=SOSA)
    assert (sosa.status_code, sosa.json()["kind"]) == (409, "prefix_in_use")
    # Tampoco una ontología propia nueva puede usarlo.
    own = b"""
@prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix dct: <http://purl.org/dc/terms/> .
@prefix adms: <http://www.w3.org/ns/adms#> . @prefix vann: <http://purl.org/vocab/vann/> .
<onto/nueva> a owl:Ontology ; owl:versionIRI <onto/nueva/1.0.0> ; owl:versionInfo "1.0.0" ;
    adms:status <http://purl.org/adms/status/Completed> ; dct:title "Nueva"@es ;
    dct:description "Prueba"@es ; vann:preferredNamespacePrefix "saref" ;
    vann:preferredNamespaceUri <onto/nueva#> .
"""
    response = api.post(
        "/ontologies?catalog=vocabularios-sinteticos",
        content=own,
        headers={**editor, "Content-Type": "text/turtle"},
    )
    assert (response.status_code, response.json()["kind"]) == (409, "prefix_in_use")
    # La propia externa sí lo recupera.
    assert post(api, editor, prefix="saref").status_code == 201


def test_version_exists_writes_nothing(
    api: TestClient, vocab_store: MemoryStore, editor: dict[str, str]
) -> None:
    """La referencia ya cuenta la versión n (otra sustitución se adelantó): 409."""
    assert post(api, editor).status_code == 201
    vocab_store.update(
        f"DELETE WHERE {{ GRAPH <{EXTERNAS}> {{ <{SAREF}> <{DCAT.hasCurrentVersion}> ?v }} }} ;"
        f"INSERT DATA {{ GRAPH <{EXTERNAS}> {{ <{SAREF}> <{DCAT.hasCurrentVersion}> <{V2}> }} }}"
    )
    taken = Graph()
    taken.add((URIRef(V2), RDF.type, PROV.Entity))
    vocab_store.put_graph(V2, taken)
    before = vocab_store.get_graph(EXTERNAS)
    response = post(api, editor)
    assert (response.status_code, response.json()["kind"]) == (409, "version_exists")
    assert isomorphic(vocab_store.get_graph(V2), taken)
    assert isomorphic(vocab_store.get_graph(EXTERNAS), before)


class FailingUpdateStore(MemoryStore):
    """Falla la primera petición de Update (y, si se pide, el borrado del grafo)."""

    def __init__(self, fail_delete: bool) -> None:
        super().__init__()
        self.fail_update = True
        self.fail_delete = fail_delete

    def update(self, request: str) -> None:
        if self.fail_update and "hasCurrentVersion" in request:
            self.fail_update = False
            raise TriplestoreError("Fuseki no responde (prueba)")
        super().update(request)

    def delete_graph(self, graph_uri: str) -> None:
        if self.fail_delete:
            raise TriplestoreError("Fuseki no responde (prueba)")
        super().delete_graph(graph_uri)


@pytest.mark.parametrize("fail_delete", [False, True])
def test_a_failure_halfway_can_be_retried(
    vocab_store: MemoryStore,
    db: Session,
    uris: Uris,
    settings: Settings,
    fake_metrics: list[str],
    fail_delete: bool,
) -> None:
    store = FailingUpdateStore(fail_delete)
    store.dataset.addN(vocab_store.dataset.quads((None, None, None, None)))
    upload = external_versions.ExternalUpload(official(), "turtle", "SAREF", "saref", SAREF)
    before = store.get_graph(EXTERNAS)
    with pytest.raises(TriplestoreError):
        external_versions.replace_external(store, db, uris, settings, "saref", upload)
    assert isomorphic(store.get_graph(EXTERNAS), before)  # la referencia no cambia
    # Sin borrar: queda un grafo huérfano, que nadie lista ni reserva prefijos.
    assert (V1 in store.graph_names()) is fail_delete
    assert vocab_ingest.reserved_external_prefixes(store, db, uris) == {}
    store.fail_delete = False
    result = external_versions.replace_external(store, db, uris, settings, "saref", upload)
    assert (result.number, result.version_uri) == (1, V1)
    assert reference(store).value(URIRef(SAREF), DCAT.hasCurrentVersion) == URIRef(V1)
    assert vocab_ingest.reserved_external_prefixes(store, db, uris) == {"saref": {SAREF}}


# --- Roles --------------------------------------------------------------------------------


def test_roles(
    api: TestClient,
    vocab_store: MemoryStore,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    editor: dict[str, str],
) -> None:
    assert post(api, None).status_code == 401
    make_user("miembro", Role.MIEMBRO)
    member = login("miembro")
    response = post(api, member)
    assert response.status_code == 403 and response.json().get("kind") is None
    make_user("admina", Role.ADMIN)
    assert post(api, login("admina")).status_code == 201
    # El resto de escrituras sobre una externa sigue dando 403 not_managed.
    for method in ("patch", "delete"):
        response = api.request(method, "/ontologies/externas/saref", headers=editor)
        assert (response.status_code, response.json()["kind"]) == (403, "not_managed")
    response = api.post(
        "/ontologies",
        content=official(),
        headers={**editor, "Content-Type": "text/turtle"},
    )
    assert (response.status_code, response.json()["kind"]) == (403, "not_managed")


# --- Concurrencia ---------------------------------------------------------------------------


class SlowStore(MemoryStore):
    def get_graph(self, graph_uri: str) -> Graph:
        graph = super().get_graph(graph_uri)
        threading.Event().wait(0.02)
        return graph


def test_simultaneous_substitutions_never_break_the_state(
    vocab_store: MemoryStore,
    tmp_path: Path,
    uris: Uris,
    settings: Settings,
    fake_metrics: list[str],
) -> None:
    """Dos sustituciones a la vez: versiones 1 y 2 (o una 409), nunca un estado roto."""
    engine = create_engine(f"sqlite:///{tmp_path / 'externas.db'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    store = SlowStore()
    store.dataset.addN(vocab_store.dataset.quads((None, None, None, None)))
    upload = external_versions.ExternalUpload(official(), "turtle", "SAREF", "saref", SAREF)

    def substitute(_index: int) -> object:
        with factory() as session:
            try:
                return external_versions.replace_external(
                    store, session, uris, settings, "saref", upload
                ).number
            except ingest.IngestError as exc:
                return exc.kind

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(substitute, range(2)), key=str)
    assert outcomes in ([1, 2], [1, "version_exists"])
    ref = reference(store)
    versions = set(ref.objects(URIRef(SAREF), DCAT.hasVersion))
    current = ref.value(URIRef(SAREF), DCAT.hasCurrentVersion)
    last = max(n for n in outcomes if isinstance(n, int))
    assert versions == {URIRef(uris.external_version("saref", n)) for n in range(1, last + 1)}
    assert current == URIRef(uris.external_version("saref", last))
    record = bajas.subject_description(store.get_graph(str(current)), current)
    external_versions.validate_records(ref, record, uris, settings)
    engine.dispose()


# --- load-semantic ------------------------------------------------------------------------


def test_load_semantic_does_not_touch_a_substituted_external(
    api: TestClient,
    vocab_store: MemoryStore,
    editor: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    file_storage: DiskStorage,
) -> None:
    assert post(api, editor, title="Título desde la aplicación").status_code == 201
    saref_before = reference(vocab_store)
    v1_before = vocab_store.get_graph(V1)
    # Una externa que no está en el fichero (no se quita) y SOSA cambiada a mano (vuelve a
    # la del fichero, sujeto a sujeto, con su publicador).
    extra = Graph()
    extra.add((URIRef("http://example.org/otra/"), RDF.type, OWL.Ontology))
    extra.add((URIRef("http://example.org/otra/"), DCT.title, Literal("Otra", lang="es")))
    vocab_store.append_graph(EXTERNAS, extra)
    vocab_store.update(
        f"DELETE WHERE {{ GRAPH <{EXTERNAS}> {{ <{SOSA}> <{DCT.title}> ?t }} }} ;"
        f'INSERT DATA {{ GRAPH <{EXTERNAS}> {{ <{SOSA}> <{DCT.title}> "Cambiada"@es }} }}'
    )

    def fake(prepared: vocab_ingest.PreparedOntology, _settings: object):
        metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri)
        return metrics.to_dict(), owl_metrics.Consistency(detail="prueba").to_dict()

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fake)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: vocab_store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: file_storage)
    get_settings.cache_clear()
    ingest.clear_caches()
    result = CliRunner().invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert f"<{SAREF}>: se omite (tiene versiones; manda la aplicación)" in result.output

    assert isomorphic(reference(vocab_store), saref_before)
    assert isomorphic(vocab_store.get_graph(V1), v1_before)
    assert not [g for g in vocab_store.graph_names() if g.startswith(f"{EXTERNAS}/sosa")]
    sosa = reference(vocab_store, SOSA)
    assert sosa.value(URIRef(SOSA), DCT.title) == Literal(
        "SOSA / SSN · Sensor, Observation, Sample and Actuator", lang="es"
    )
    assert sosa.value(sosa.value(URIRef(SOSA), DCT.publisher), FOAF.name) == Literal("W3C")
    assert len(list(sosa.objects(URIRef(SOSA), DCT.publisher))) == 1
    assert (URIRef("http://example.org/otra/"), RDF.type, OWL.Ontology) in vocab_store.get_graph(
        EXTERNAS
    )
    # Y una segunda carga no cambia nada.
    again = CliRunner().invoke(cli_module.cli, ["load-semantic"])
    assert again.exit_code == 0, again.output
    assert f"<{SOSA}> -> <{EXTERNAS}>: sin cambios" in again.output


# --- Métricas -----------------------------------------------------------------------------


def test_metrics_count_the_reference_namespace(uris: Uris, settings: Settings) -> None:
    """owlready2 y Pellet de verdad, sin descargar los owl:imports."""
    graph = Graph().parse(data=official().decode(), format="turtle")
    metrics, consistency = external_versions.compute_external_metrics(graph, SAREF, SAREF, settings)
    assert (metrics["classes"], metrics["imports"]) == (2, 1)
    assert metrics["documentation"]["classes_documented"] == 1
    assert consistency["reasoner"] == "Pellet"
    if owl_metrics.java_available():
        assert consistency["consistent"] is True
    # Con otro espacio de nombres cuentan otras clases.
    assert owl_metrics.compute_metrics(graph, SAREF, "http://otra.example.org/").classes == 1


def test_metrics_are_stored_per_version(
    api: TestClient, editor: dict[str, str], session_factory: sessionmaker[Session]
) -> None:
    assert post(api, editor).status_code == 201
    with session_factory() as session:
        record = session.get(OntologyMetricsRecord, V1)
    assert record is not None and record.ontology_iri == SAREF
    assert record.metrics["classes"] == 2


# --- Resolución de URIs y SPARQL ------------------------------------------------------------


def test_uri_resolution(api: TestClient, editor: dict[str, str], settings: Settings) -> None:
    front = settings.frontend_base_url
    # Sin versiones: la serie va a la ficha (HTML) y no tiene RDF.
    response = api.get("/onto/externas/saref", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (
        303,
        f"{front}/ontologias/externas/saref",
    )
    assert api.get("/onto/externas/saref", headers=TURTLE).status_code == 404
    assert post(api, editor).status_code == 201

    response = api.get("/onto/externas/saref", headers=TURTLE, follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (303, V1)
    response = api.get("/onto/externas/saref/1", headers=TURTLE)
    assert response.status_code == 200
    graph = Graph().parse(data=response.text, format="turtle")
    assert (URIRef(V1), DCT.isVersionOf, URIRef(SAREF)) in graph
    assert (URIRef(SAREF), OWL.versionIRI, URIRef(f"{SAREF}v9.9.9/")) in graph
    response = api.get("/onto/externas/saref/1", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (
        303,
        f"{front}/ontologias/externas/saref?version=1",
    )
    response = api.get("/onto/externas/saref/1", headers={"Accept": "application/ld+json"})
    assert response.status_code == 200
    assert api.get("/onto/externas/saref/2", headers=TURTLE).status_code == 404
    assert api.get("/onto/externas/saref/01", headers=TURTLE).status_code == 422
    assert api.get("/onto/externas/nada", headers=TURTLE).status_code == 404
    assert api.get("/onto/externas/nada/1", headers=TURTLE).status_code == 404
    # RDF por la API (para descargar), la actual o ?version=.
    rdf = api.get("/ontologies/externas/saref/rdf", params={"format": "turtle"})
    assert rdf.status_code == 200 and str(DCT.isVersionOf) in Graph().parse(
        data=rdf.text, format="turtle"
    ).serialize(format="nt")
    assert api.get("/ontologies/externas/sosa/rdf").status_code == 404
    assert api.get("/ontologies/externas/saref/rdf", params={"version": "2"}).status_code == 404


def test_sparql_sees_the_version_graphs(api: TestClient, editor: dict[str, str]) -> None:
    assert post(api, editor).status_code == 201
    query = "SELECT ?g ?o WHERE { GRAPH ?g { ?g <http://purl.org/dc/terms/isVersionOf> ?o } }"
    response = api.get(
        "/sparql",
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["results"]["bindings"]
    assert [(r["g"]["value"], r["o"]["value"]) for r in rows] == [(V1, SAREF)]
