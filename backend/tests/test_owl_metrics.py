"""Métricas OWL (owlready2), perfil aproximado, consistencia (Pellet) y ausencia de red.

Las pruebas de Pellet necesitan Java. En local y en los runners de GitHub Actions
(ubuntu-latest trae un JDK) se ejecutan; si no hay Java, se saltan con el motivo.
"""

import socket
import subprocess
from pathlib import Path

import pytest
from rdflib import Graph

from app import owl_metrics
from tests.conftest import BASE_URI, FIXTURE_COUNTS_ONTOLOGY

ONTO = f"{BASE_URI}onto/itot"
FIXTURE_120 = FIXTURE_COUNTS_ONTOLOGY

requires_java = pytest.mark.skipif(
    not owl_metrics.java_available(), reason="Pellet necesita Java y no está en el PATH"
)

HEADER = f"""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix : <{ONTO}#> .
<{ONTO}> a owl:Ontology ; owl:versionIRI <{ONTO}/9.0.0> .
"""


def _graph(body: str) -> Graph:
    return Graph().parse(data=HEADER + body, format="turtle")


def _fixture() -> Graph:
    return Graph().parse(FIXTURE_120, format="turtle", publicID=BASE_URI)


def _consistency(graph: Graph, **kwargs: float) -> owl_metrics.Consistency:
    options = {"timeout_seconds": 120.0, "java_memory_mb": 512} | kwargs
    return owl_metrics.check_consistency(graph, ONTO, **options)  # type: ignore[arg-type]


# --- Recuentos ---------------------------------------------------------------------------


def test_metrics_of_fixture_have_known_counts() -> None:
    metrics = owl_metrics.compute_metrics(_fixture(), ONTO)
    assert metrics.classes == 3
    assert metrics.object_properties == 1
    assert metrics.data_properties == 1
    assert metrics.annotation_properties == 0
    assert metrics.individuals == 1
    assert metrics.logical_axioms == 8
    assert metrics.imports == 1
    assert metrics.import_iris == ["https://example.org/externa/sensores"]
    assert metrics.dl_expressivity is None
    assert metrics.profile == "OWL 2 DL"
    assert metrics.compatible_profiles == ["OWL 2 EL", "OWL 2 QL", "OWL 2 RL"]
    doc = metrics.documentation
    assert (doc.documented, doc.total, doc.percent) == (3, 5, 60.0)
    assert (doc.classes_documented, doc.classes_total) == (2, 3)
    assert (doc.properties_documented, doc.properties_total) == (1, 2)


def test_logical_axioms_count_each_kind_once() -> None:
    graph = _graph(
        """
        :A a owl:Class . :B a owl:Class . :C a owl:Class .
        :A owl:equivalentClass :B .                         # 1
        :A owl:disjointWith :C .                            # 2
        [] a owl:AllDisjointClasses ; owl:members (:A :B :C) .  # 3
        :p a owl:ObjectProperty , owl:TransitiveProperty ;  # 4 (característica)
           owl:inverseOf :q ;                               # 5
           rdfs:subPropertyOf :r .                          # 6
        :q a owl:ObjectProperty . :r a owl:ObjectProperty .
        :n a owl:AnnotationProperty ; rdfs:domain :A .      # no cuenta (anotación)
        :i a owl:NamedIndividual , :A ;                     # 7 (aserción de clase)
           :p :j ;                                          # 8 (aserción de propiedad)
           owl:sameAs :k .                                  # 9
        :j a owl:NamedIndividual .
        """
    )
    metrics = owl_metrics.compute_metrics(graph, ONTO)
    assert metrics.logical_axioms == 9
    assert metrics.annotation_properties == 1
    assert metrics.individuals == 2
    assert metrics.documentation.percent == 0.0


def test_only_own_namespace_entities_are_counted() -> None:
    """Declaraciones de términos externos (para seguir en OWL 2 DL sin los imports) no
    cuentan como clases ni propiedades propias."""
    graph = _graph(
        """
        @prefix d3f: <http://d3fend.mitre.org/ontologies/d3fend.owl#> .
        @prefix dct: <http://purl.org/dc/terms/> .
        :Control a owl:Class ; rdfs:subClassOf d3f:DefensiveTechnique .
        d3f:DefensiveTechnique a owl:Class .
        dct:title a owl:AnnotationProperty .
        <http://otra.example/p> a owl:ObjectProperty .
        """
    )
    metrics = owl_metrics.compute_metrics(graph, ONTO)
    assert metrics.classes == 1
    assert metrics.annotation_properties == 0
    assert metrics.object_properties == 0
    assert metrics.documentation.total == 1


def test_empty_ontology_has_no_coverage_percent() -> None:
    metrics = owl_metrics.compute_metrics(_graph(""), ONTO)
    assert metrics.classes == 0
    assert metrics.documentation.total == 0
    assert metrics.documentation.percent is None


# --- Perfil aproximado -------------------------------------------------------------------


def test_profile_full_when_property_is_object_and_data() -> None:
    graph = _graph(":p a owl:ObjectProperty , owl:DatatypeProperty .")
    metrics = owl_metrics.compute_metrics(graph, ONTO)
    assert metrics.profile == "OWL 2 Full"
    assert metrics.compatible_profiles == []


@pytest.mark.parametrize(
    ("body", "excluded"),
    [
        (":A a owl:Class ; owl:unionOf (:B :C) .", {"OWL 2 EL", "OWL 2 QL"}),
        (
            ":A a owl:Class ; rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :p ; "
            'owl:minCardinality "2"^^xsd:nonNegativeInteger ] . :p a owl:ObjectProperty .',
            {"OWL 2 EL", "OWL 2 QL", "OWL 2 RL"},
        ),
        (
            ":A a owl:Class ; rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :p ; "
            "owl:someValuesFrom :B ] . :p a owl:ObjectProperty . :B a owl:Class .",
            {"OWL 2 RL"},
        ),
        (":p a owl:ObjectProperty , owl:FunctionalProperty .", {"OWL 2 EL", "OWL 2 QL"}),
        (":d a owl:DatatypeProperty , owl:FunctionalProperty .", {"OWL 2 QL"}),
    ],
)
def test_profile_excludes_by_constructs(body: str, excluded: set[str]) -> None:
    metrics = owl_metrics.compute_metrics(_graph(body), ONTO)
    assert metrics.profile == "OWL 2 DL"
    compatible = set(metrics.compatible_profiles)
    assert not compatible & excluded
    assert compatible == {"OWL 2 EL", "OWL 2 QL", "OWL 2 RL"} - excluded


# --- Consistencia (Pellet) ---------------------------------------------------------------


@requires_java
def test_consistent_fixture() -> None:
    result = _consistency(_fixture())
    assert result.reasoner == "Pellet"
    assert result.consistent is True
    assert result.unsatisfiable_classes == 0
    assert result.unsatisfiable == []
    assert result.detail is None


@requires_java
def test_unsatisfiable_classes_are_counted() -> None:
    graph = _graph(
        """
        :A a owl:Class . :B a owl:Class ; rdfs:subClassOf :A .
        :C a owl:Class ; rdfs:subClassOf :B .
        :A owl:disjointWith :B .
        """
    )
    result = _consistency(graph)
    assert result.consistent is True
    assert result.unsatisfiable_classes == 2
    assert result.unsatisfiable == [f"{ONTO}#B", f"{ONTO}#C"]


@requires_java
def test_inconsistent_ontology() -> None:
    graph = _graph(
        """
        :A a owl:Class . :B a owl:Class . :A owl:disjointWith :B .
        :x a owl:NamedIndividual , :A , :B .
        """
    )
    result = _consistency(graph)
    assert result.reasoner == "Pellet"
    assert result.consistent is False
    assert result.unsatisfiable_classes is None
    assert "inconsistente" in (result.detail or "")


@requires_java
def test_reasoner_timeout_is_reported_not_raised() -> None:
    result = _consistency(_fixture(), timeout_seconds=0.001)
    assert result.consistent is None
    assert "tiempo" in (result.detail or "")


def test_old_java_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(owl_metrics, "java_major_version", lambda: 21)
    result = _consistency(_fixture())
    assert result.consistent is None
    assert "Java 25" in (result.detail or "") and "21" in (result.detail or "")


def test_missing_java_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    import owlready2

    monkeypatch.setattr(owlready2, "JAVA_EXE", "java-que-no-existe-en-el-path")
    owl_metrics.java_major_version.cache_clear()
    try:
        result = _consistency(_fixture())
    finally:
        owl_metrics.java_major_version.cache_clear()
    assert result.consistent is None
    assert result.unsatisfiable_classes is None
    assert "Java" in (result.detail or "")


@requires_java
def test_owlready2_globals_are_restored() -> None:
    from owlready2 import reasoning

    before_memory, before_kargs = reasoning.JAVA_MEMORY, dict(reasoning._subprocess_kargs)
    _consistency(_fixture(), java_memory_mb=300)
    assert before_memory == reasoning.JAVA_MEMORY
    assert reasoning._subprocess_kargs == before_kargs


# --- Sin red -------------------------------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Cualquier conexión de red desde Python falla y queda registrada."""
    attempts: list[object] = []

    def refuse(*args: object, **_kwargs: object) -> None:
        attempts.append(args)
        raise OSError("red prohibida en esta prueba")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return attempts


IMPORTS = """
<{onto}> owl:imports <https://www.w3.org/ns/sosa/> , <http://127.0.0.1:9/no-existe.owl> ,
    <https://saref.etsi.org/core/> .
:Sensor a owl:Class ; rdfs:subClassOf <http://www.w3.org/ns/sosa/Sensor> .
""".replace("{onto}", ONTO)


def test_metrics_never_download_imports(no_network: list[object]) -> None:
    metrics = owl_metrics.compute_metrics(_graph(IMPORTS), ONTO)
    assert metrics.imports == 3
    assert metrics.classes == 1
    assert no_network == []


@requires_java
def test_reasoning_never_downloads_imports(
    no_network: list[object], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Python no abre conexiones y Pellet recibe un fichero sin owl:imports y con
    ``--ignore-imports``."""
    from owlready2 import reasoning

    seen: dict[str, object] = {}
    real_run = subprocess.run

    def spy(command: list[str], *args: object, **kwargs: object) -> object:
        seen["command"] = list(command)
        seen["input"] = Path(command[-1]).read_text(encoding="utf-8")
        return real_run(command, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(reasoning.subprocess, "run", spy)
    result = _consistency(_graph(IMPORTS))
    assert result.consistent is True
    assert no_network == []
    assert "--ignore-imports" in seen["command"]  # type: ignore[operator]
    assert "owl#imports" not in seen["input"]  # type: ignore[operator]
    assert "sosa" in seen["input"]  # la referencia a la clase externa sí está


def test_without_imports_keeps_everything_else() -> None:
    graph = _graph(IMPORTS)
    stripped = owl_metrics.without_imports(graph)
    assert len(stripped) == len(graph) - 3
    assert owl_metrics.declared_imports(graph) == sorted(
        [
            "https://www.w3.org/ns/sosa/",
            "http://127.0.0.1:9/no-existe.owl",
            "https://saref.etsi.org/core/",
        ]
    )
