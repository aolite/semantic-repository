"""Métricas OWL y consistencia de una versión de ontología (decisión del responsable,
2026-11-15: owlready2 y Pellet).

Se calculan **en la ingesta** (``POST /ontologies`` y ``load-semantic``) y se guardan en
PostgreSQL (``app.models.OntologyMetricsRecord``); la lectura no las recalcula.

**Sin red.** Los ``owl:imports`` no se descargan nunca: antes de pasar el grafo a
owlready2 se quitan los triples ``owl:imports`` (owlready2 intentaría cargar cada
ontología importada desde ``onto_path`` o desde la web). Por eso:

- ``imports`` cuenta los ``owl:imports`` **declarados**, no lo que contienen.
- El razonamiento se hace **sin las ontologías importadas**: Pellet solo ve los axiomas
  de la propia ontología. Una inconsistencia que dependa de axiomas de SOSA o SAREF no
  se detecta, y las clases externas se tratan como clases sin axiomas.

Qué cuenta cada métrica:

- ``classes``, ``object_properties``, ``data_properties``, ``annotation_properties`` e
  ``individuals``: entidades con nombre declaradas en la ontología, tal como las devuelve
  owlready2 (``classes()``, ``object_properties()``… e ``individuals()``, que son los
  ``owl:NamedIndividual``), **solo las del espacio de nombres propio**
  ``{ontología}#``. Las declaraciones de términos externos que la ontología repite para
  seguir en OWL 2 DL sin sus imports (``d3f:DefensiveTechnique a owl:Class``,
  ``dct:title a owl:AnnotationProperty``) no cuentan.
- ``logical_axioms``: owlready2 no expone un recuento de axiomas, así que se cuentan
  sobre el mismo grafo los triples que, en el mapeo de OWL 2 a RDF, corresponden a un
  axioma lógico (``_count_logical_axioms``). Es una aproximación del
  ``getLogicalAxiomCount`` de la OWL API: puede diferir en casos raros (axiomas n-arios
  escritos de varias formas, aserciones sobre nodos en blanco).
- ``dl_expressivity``: no se calcula (decisión del responsable); siempre ``None``.
- Perfil (``_profile``): **aproximado por constructores**. ``OWL 2 Full`` si hay un
  choque de tipos que OWL 2 DL no admite (una IRI que es a la vez propiedad de objeto y
  de datos, o clase y tipo de datos); si no, ``OWL 2 DL``. Además se listan los perfiles
  EL, QL y RL compatibles: un perfil se descarta si aparece algún constructor que no
  admite, y para RL también por la posición de algunas expresiones en
  ``rdfs:subClassOf``. No es un validador de perfiles completo (no comprueba todas las
  restricciones de posición), así que puede declarar compatible un perfil que no lo es.
- Cobertura de documentación: porcentaje de clases y propiedades (de objeto y de datos)
  con al menos un ``rdfs:comment``.
"""

import io
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from threading import Lock
from typing import Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

REASONER_NAME = "Pellet"

# owlready2 mantiene estado global (mundo por defecto, espacios de nombres activos): se
# serializa el uso para no mezclar dos ingestas simultáneas.
_LOCK = Lock()


@dataclass
class DocumentationCoverage:
    documented: int
    total: int
    percent: float | None
    classes_documented: int
    classes_total: int
    properties_documented: int
    properties_total: int


@dataclass
class OntologyMetrics:
    classes: int
    object_properties: int
    data_properties: int
    annotation_properties: int
    individuals: int
    logical_axioms: int
    imports: int
    import_iris: list[str]
    profile: str
    compatible_profiles: list[str]
    documentation: DocumentationCoverage
    dl_expressivity: None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Consistency:
    reasoner: str = REASONER_NAME
    consistent: bool | None = None
    unsatisfiable_classes: int | None = None
    unsatisfiable: list[str] = field(default_factory=list)
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Preparación ----------------------------------------------------------------------


def without_imports(graph: Graph) -> Graph:
    """Copia del grafo sin ``owl:imports``: owlready2 no intentará descargar nada."""
    result = Graph()
    for triple in graph:
        if triple[1] != OWL.imports:
            result.add(triple)
    return result


def declared_imports(graph: Graph) -> list[str]:
    return sorted({str(o) for o in graph.objects(None, OWL.imports) if isinstance(o, URIRef)})


def _load_world(graph: Graph, ontology_iri: str) -> tuple[Any, Any]:
    """Mundo de owlready2 en memoria con el grafo (sin imports). Lo llama quien tiene
    ``_LOCK``."""
    import owlready2

    world = owlready2.World()
    data = without_imports(graph).serialize(format="nt", encoding="utf-8")
    onto = world.get_ontology(ontology_iri).load(fileobj=io.BytesIO(data), format="ntriples")
    return world, onto


def _named(entities: Iterable[Any], namespace: str) -> set[str]:
    """IRIs de las entidades con nombre que están en ``namespace``."""
    return {
        str(e.iri)
        for e in entities
        if getattr(e, "iri", None) and str(e.iri).startswith(namespace)
    }


# --- Métricas -------------------------------------------------------------------------

_CHARACTERISTICS = {
    OWL.FunctionalProperty,
    OWL.InverseFunctionalProperty,
    OWL.TransitiveProperty,
    OWL.SymmetricProperty,
    OWL.AsymmetricProperty,
    OWL.ReflexiveProperty,
    OWL.IrreflexiveProperty,
}
_COUNT_EACH_TRIPLE = {
    RDFS.subClassOf,
    OWL.equivalentClass,
    OWL.disjointWith,
    OWL.disjointUnionOf,
    RDFS.subPropertyOf,
    OWL.equivalentProperty,
    OWL.inverseOf,
    OWL.propertyDisjointWith,
    OWL.propertyChainAxiom,
    OWL.hasKey,
    OWL.sameAs,
    OWL.differentFrom,
}
_NARY_TYPES = {
    OWL.AllDisjointClasses,
    OWL.AllDisjointProperties,
    OWL.AllDifferent,
    OWL.NegativePropertyAssertion,
}
# Clases del propio vocabulario RDF/RDFS/OWL: un rdf:type hacia ellas es una declaración
# o una construcción, no una aserción de clase.
_BUILTIN_NAMESPACES = (str(RDF), str(RDFS), str(OWL), str(XSD))


def _is_builtin(node: Any) -> bool:
    return isinstance(node, URIRef) and str(node).startswith(_BUILTIN_NAMESPACES)


def _count_logical_axioms(graph: Graph) -> int:
    object_props = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    data_props = set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    asserted_props = object_props | data_props
    count = 0
    for subject, predicate, obj in graph:
        if predicate in _COUNT_EACH_TRIPLE:
            count += 1
        elif predicate in (RDFS.domain, RDFS.range):
            # Dominio y rango de propiedades de anotación no son axiomas lógicos.
            count += subject in asserted_props
        elif predicate == RDF.type:
            if obj in _CHARACTERISTICS or obj in _NARY_TYPES:
                count += 1
            elif isinstance(subject, URIRef) and not _is_builtin(obj):
                count += 1  # aserción de clase sobre un individuo
        elif predicate in asserted_props and isinstance(subject, URIRef):
            count += 1  # aserción de propiedad de objeto o de datos
    return count


def _coverage(graph: Graph, classes: set[str], properties: set[str]) -> DocumentationCoverage:
    def documented(iris: set[str]) -> int:
        return sum(
            1
            for value in iris
            if any(isinstance(c, Literal) for c in graph.objects(URIRef(value), RDFS.comment))
        )

    classes_doc = documented(classes)
    props_doc = documented(properties)
    total = len(classes) + len(properties)
    done = classes_doc + props_doc
    return DocumentationCoverage(
        documented=done,
        total=total,
        percent=round(100 * done / total, 1) if total else None,
        classes_documented=classes_doc,
        classes_total=len(classes),
        properties_documented=props_doc,
        properties_total=len(properties),
    )


# --- Perfil (aproximado) --------------------------------------------------------------

_CARDINALITIES = {
    OWL.minCardinality,
    OWL.maxCardinality,
    OWL.cardinality,
    OWL.minQualifiedCardinality,
    OWL.maxQualifiedCardinality,
    OWL.qualifiedCardinality,
}
_NOT_EL = {
    OWL.allValuesFrom,
    OWL.unionOf,
    OWL.complementOf,
    OWL.inverseOf,
    OWL.disjointUnionOf,
    OWL.propertyDisjointWith,
    OWL.AllDisjointProperties,
    OWL.SymmetricProperty,
    OWL.AsymmetricProperty,
    OWL.IrreflexiveProperty,
    OWL.InverseFunctionalProperty,
    *_CARDINALITIES,
}
_NOT_QL = {
    OWL.unionOf,
    OWL.oneOf,
    OWL.allValuesFrom,
    OWL.hasValue,
    OWL.hasSelf,
    OWL.propertyChainAxiom,
    OWL.hasKey,
    OWL.sameAs,
    OWL.disjointUnionOf,
    OWL.FunctionalProperty,
    OWL.InverseFunctionalProperty,
    OWL.TransitiveProperty,
    *_CARDINALITIES,
}
_NOT_RL = {
    OWL.hasSelf,
    OWL.disjointUnionOf,
    OWL.ReflexiveProperty,
    OWL.minCardinality,
    OWL.cardinality,
    OWL.minQualifiedCardinality,
    OWL.qualifiedCardinality,
}


def _constructs(graph: Graph) -> set[URIRef]:
    used: set[URIRef] = set()
    for _s, predicate, obj in graph:
        used.add(predicate)  # type: ignore[arg-type]
        if predicate == RDF.type and isinstance(obj, URIRef):
            used.add(obj)
    return used


def _el_extra(graph: Graph) -> bool:
    """EL: owl:oneOf de un solo individuo; propiedades funcionales solo de datos."""
    for node in graph.objects(None, OWL.oneOf):
        if len(list(Collection(graph, node))) > 1:
            return False
    data_props = set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    return all(p in data_props for p in graph.subjects(RDF.type, OWL.FunctionalProperty))


def _rl_extra(graph: Graph) -> bool:
    """RL, por posición en rdfs:subClassOf y por el valor de las cardinalidades."""
    for sub, sup in graph.subject_objects(RDFS.subClassOf):
        if isinstance(sup, BNode) and (
            (sup, OWL.someValuesFrom, None) in graph or (sup, OWL.unionOf, None) in graph
        ):
            return False
        if isinstance(sub, BNode) and (sub, OWL.allValuesFrom, None) in graph:
            return False
    for prop in (OWL.maxCardinality, OWL.maxQualifiedCardinality):
        for value in graph.objects(None, prop):
            if not (isinstance(value, Literal) and str(value) in {"0", "1"}):
                return False
    return True


def _profile(graph: Graph) -> tuple[str, list[str]]:
    object_props = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    data_props = set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    classes = set(graph.subjects(RDF.type, OWL.Class))
    datatypes = set(graph.subjects(RDF.type, RDFS.Datatype))
    if object_props & data_props or classes & datatypes:
        return "OWL 2 Full", []
    used = _constructs(graph)
    compatible = []
    if not used & _NOT_EL and _el_extra(graph):
        compatible.append("OWL 2 EL")
    if not used & _NOT_QL:
        compatible.append("OWL 2 QL")
    if not used & _NOT_RL and _rl_extra(graph):
        compatible.append("OWL 2 RL")
    return "OWL 2 DL", compatible


def compute_metrics(graph: Graph, ontology_iri: str) -> OntologyMetrics:
    """Métricas de la versión. El grafo es el de la versión, con sus ``owl:imports``."""
    imports = declared_imports(graph)
    plain = without_imports(graph)
    own = f"{ontology_iri}#"
    with _LOCK:
        _world, onto = _load_world(graph, ontology_iri)
        classes = _named(onto.classes(), own)
        object_props = _named(onto.object_properties(), own)
        data_props = _named(onto.data_properties(), own)
        annotation_props = _named(onto.annotation_properties(), own)
        individuals = _named(onto.individuals(), own)
    profile, compatible = _profile(plain)
    return OntologyMetrics(
        classes=len(classes),
        object_properties=len(object_props),
        data_properties=len(data_props),
        annotation_properties=len(annotation_props),
        individuals=len(individuals),
        logical_axioms=_count_logical_axioms(plain),
        imports=len(imports),
        import_iris=imports,
        profile=profile,
        compatible_profiles=compatible,
        documentation=_coverage(plain, classes, object_props | data_props),
    )


# --- Consistencia ---------------------------------------------------------------------


# El Jena que owlready2 0.51 incluye para Pellet está compilado para Java 25.
MIN_JAVA_MAJOR = 25
_JAVA_VERSION = re.compile(r'version "(\d+)(?:\.(\d+))?')


@lru_cache(maxsize=1)
def java_major_version() -> int | None:
    """Versión mayor de ``java`` en el PATH (``None`` si no hay Java)."""
    import owlready2

    executable = shutil.which(owlready2.JAVA_EXE)
    if executable is None:
        return None
    try:
        output = subprocess.run(  # noqa: S603 - ejecutable resuelto en el PATH, sin shell
            [executable, "-version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = _JAVA_VERSION.search(output.stderr + output.stdout)
    if match is None:
        return None
    major = int(match.group(1))
    return int(match.group(2) or 0) if major == 1 else major  # "1.8" -> 8


def java_available() -> bool:
    """Hay Java y es al menos ``MIN_JAVA_MAJOR``."""
    major = java_major_version()
    return major is not None and major >= MIN_JAVA_MAJOR


def check_consistency(
    graph: Graph, ontology_iri: str, *, timeout_seconds: float, java_memory_mb: int
) -> Consistency:
    """Pellet (incluido en owlready2) sobre la ontología sin sus imports.

    No lanza excepciones por fallos del razonador: si Java no está, Pellet falla o se
    agota el tiempo, devuelve ``consistent=None`` con el motivo en ``detail``.
    """
    import owlready2
    from owlready2 import reasoning

    if not java_available():
        major = java_major_version()
        found = "no está en el PATH" if major is None else f"es la versión {major}"
        return Consistency(
            detail=f"Pellet necesita Java {MIN_JAVA_MAJOR} o superior y Java {found}: "
            "no se ha ejecutado"
        )
    with _LOCK:
        world, _onto = _load_world(graph, ontology_iri)
        previous_memory = reasoning.JAVA_MEMORY
        previous_kargs = dict(reasoning._subprocess_kargs)
        reasoning.JAVA_MEMORY = java_memory_mb
        # owlready2 pasa estos argumentos a subprocess.run: así Pellet tiene un límite de
        # tiempo y el proceso Java se mata si lo supera.
        reasoning._subprocess_kargs["timeout"] = timeout_seconds
        try:
            owlready2.sync_reasoner_pellet(world, infer_property_values=False, debug=0)
        except owlready2.OwlReadyInconsistentOntologyError:
            return Consistency(consistent=False, detail="La ontología es inconsistente")
        except subprocess.TimeoutExpired:
            return Consistency(detail=f"Pellet superó el tiempo máximo ({timeout_seconds:g} s)")
        except (owlready2.OwlReadyJavaError, OSError) as exc:
            first_line = (str(exc).strip().splitlines() or [""])[-1][:300]
            return Consistency(detail=f"Pellet falló: {first_line}")
        finally:
            reasoning.JAVA_MEMORY = previous_memory
            reasoning._subprocess_kargs.clear()
            reasoning._subprocess_kargs.update(previous_kargs)
        unsatisfiable = sorted(
            str(c.iri) for c in world.inconsistent_classes() if c is not owlready2.Nothing
        )
    return Consistency(
        consistent=True,
        unsatisfiable_classes=len(unsatisfiable),
        unsatisfiable=unsatisfiable,
    )
