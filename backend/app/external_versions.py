"""Versiones de las ontologías externas (decisión 51, ``semantic/uris.md``, «Versiones de
las ontologías externas»).

Una externa conserva su IRI oficial y su **registro de referencia** en el grafo
``{BASE_URI}onto/externas``. Cada sustitución entera desde la aplicación crea una versión
``{BASE_URI}onto/externas/{slug}/{n}`` (``n`` = 1, 2, 3…; ``slug`` = el prefijo VANN de la
primera sustitución), que vive en el grafo de su URI con dos cosas:

- el **fichero oficial completo**, tal como lo publica su organismo (no se valida con las
  formas: es contenido ajeno);
- el **registro de la versión** (``prov:Entity`` con ``dct:isVersionOf``, ``dcat:version``,
  ``owl:versionInfo``, ``prov:generatedAtTime``, ``dcat:previousVersion``,
  ``prov:wasRevisionOf`` y ``adms:versionNotes``), que construye el backend.

La referencia lista sus versiones con ``dcat:hasVersion`` y la actual (la última) con
``dcat:hasCurrentVersion``. Los grafos de versión son inmutables.

Sustitución (``replace_external``):

1. Fuera del bloqueo: la externa existe (404), los campos del formulario, el fichero (se
   analiza, declara ``<IRI oficial> a owl:Ontology`` y no describe recursos bajo
   ``BASE_URI``: 422), el SHACL de la referencia y la versión juntas (422) y las métricas y
   la consistencia (owlready2 y Pellet, sin descargar los ``owl:imports``), calculadas sobre
   el fichero oficial y contando como propias las entidades del espacio de nombres de la
   referencia.
2. Con el bloqueo de las escrituras del catálogo (``app.write_lock``, que serializa todas
   las sustituciones): se vuelve a leer la referencia, ``n`` = última + 1, prefijo libre
   (409 ``prefix_withdrawn`` o ``prefix_in_use``) y grafo de la versión libre (409
   ``version_exists``).
3. Escritura: primero PostgreSQL (prefijo de la versión y métricas, filas que solo cuentan
   si la versión llega a la referencia), después el grafo de la versión (``PUT``, atómico) y
   por último **una** petición de Update que reescribe solo el registro de esa externa en
   ``{BASE_URI}onto/externas``. Si esa última falla, se intenta borrar el grafo recién
   escrito; si tampoco se puede, queda un grafo huérfano que no lista la referencia, que
   ninguna lectura de la API muestra y que la siguiente sustitución (el mismo ``n``)
   sobrescribe. Así un reintento siempre es seguro.
4. Auditoría ``external_ontology_replaced``.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD
from sqlalchemy.orm import Session

from app import audit, bajas, ingest, owl_metrics, schemas, vocab_ingest, vocabularies
from app.catalog import pick_literal
from app.config import Settings
from app.ingest import IngestError, Issue
from app.models import AuditAction, ExternalVersionPrefix, OntologyMetricsRecord, User
from app.sparql import iri, literal, render
from app.triplestore import TripleStore, TriplestoreError
from app.uris import ADMS, DCAT, DCT, FOAF, PROV, VANN, Uris, is_slug
from app.write_lock import catalog_write_lock

logger = logging.getLogger(__name__)

PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")
# Placeholders del prototipo («[VERSIÓN]»): owl:versionInfo se omite (semantic/uris.md).
PLACEHOLDER = re.compile(r"^\[[^\]]*\]$")
MAX_TITLE = 300
MAX_TEXT = 4000


class ExternalNotFoundError(LookupError):
    """La externa no existe en ``{BASE_URI}onto/externas``."""


# --- Lectura de la referencia ---------------------------------------------------------


@dataclass
class ExternalInfo:
    """Una ontología externa del grafo ``{BASE_URI}onto/externas``."""

    uri: str
    slug: str | None
    prefix: str | None
    versions: dict[int, str]  # n -> URI de la versión (las de dcat:hasVersion)
    current: str | None  # dcat:hasCurrentVersion

    @property
    def last(self) -> int:
        return max(self.versions, default=0)


def reference_graph(store: TripleStore, uris: Uris) -> Graph:
    return store.get_graph(uris.external_ontologies_graph)


def _literal(graph: Graph, node: URIRef, prop: URIRef) -> str | None:
    values = sorted(str(v) for v in graph.objects(node, prop) if isinstance(v, Literal))
    return values[0] if values else None


def external_info(graph: Graph, uris: Uris, node: URIRef) -> ExternalInfo:
    """Slug de una externa: el de sus versiones si tiene; si no, su prefijo VANN (el slug
    que tendrá en su primera sustitución), o ``None`` si no tiene un prefijo válido."""
    versions: dict[int, str] = {}
    slugs: set[str] = set()
    for value in graph.objects(node, DCAT.hasVersion):
        parts = uris.external_version_parts(str(value))
        if isinstance(value, URIRef) and parts is not None:
            slugs.add(parts[0])
            versions[parts[1]] = str(value)
    prefix = _literal(graph, node, VANN.preferredNamespacePrefix)
    if slugs:
        slug: str | None = sorted(slugs)[0]
    else:
        slug = prefix if prefix and is_slug(prefix) else None
    current = graph.value(node, DCAT.hasCurrentVersion)
    return ExternalInfo(
        uri=str(node),
        slug=slug,
        prefix=prefix,
        versions=versions,
        current=str(current) if isinstance(current, URIRef) else None,
    )


def externals(graph: Graph, uris: Uris) -> list[ExternalInfo]:
    nodes = {n for n in graph.subjects(RDF.type, OWL.Ontology) if isinstance(n, URIRef)}
    return [external_info(graph, uris, n) for n in sorted(nodes, key=str)]


def find_external(graph: Graph, uris: Uris, slug: str) -> ExternalInfo:
    """La externa de ``slug``: primero la que ya tiene versiones con ese slug (el slug no
    cambia aunque cambie el prefijo) y si no, la que no tiene versiones y usa ese prefijo."""
    candidates = [e for e in externals(graph, uris) if e.slug == slug]
    candidates.sort(key=lambda e: (not e.versions, e.uri))
    if not candidates:
        raise ExternalNotFoundError(slug)
    return candidates[0]


# --- Formulario y fichero ---------------------------------------------------------------


@dataclass
class ExternalUpload:
    """Lo que llega en la sustitución: el fichero completo y los metadatos de referencia."""

    data: bytes
    rdf_format: ingest.RdfFormat
    title: str
    prefix: str
    namespace: str
    description: str | None = None
    version_info: str | None = None
    publisher: str | None = None
    version_notes: str | None = None


def _has_control(value: str, *, multiline: bool) -> bool:
    allowed = "\n\r\t" if multiline else ""
    return any((ord(c) < 0x20 and c not in allowed) or ord(c) == 0x7F for c in value)


def check_fields(upload: ExternalUpload) -> None:
    """422 ``structure`` con un problema por campo (``path`` = nombre del campo)."""
    issues: list[Issue] = []

    def bad(name: str, message: str) -> None:
        issues.append(Issue(message, path=name))

    for name, value, limit, multiline, required in (
        ("title", upload.title, MAX_TITLE, False, True),
        ("description", upload.description, MAX_TEXT, True, False),
        ("version_info", upload.version_info, MAX_TITLE, False, False),
        ("publisher", upload.publisher, MAX_TITLE, False, False),
        ("version_notes", upload.version_notes, MAX_TEXT, True, False),
    ):
        if value is None or not value.strip():
            if required:
                bad(name, "Campo obligatorio")
            continue
        if len(value) > limit:
            bad(name, f"Como mucho {limit} caracteres")
        elif _has_control(value, multiline=multiline):
            bad(name, "No puede contener caracteres de control")
    if not PREFIX_PATTERN.fullmatch(upload.prefix or ""):
        bad("prefix", "Prefijo VANN en minúsculas ASCII y dígitos, empezando por letra (saref)")
    try:
        iri(upload.namespace or "")
    except ValueError:
        bad("namespace", "Espacio de nombres: una IRI http(s) válida")
    if issues:
        raise IngestError("structure", "Hay campos del formulario que no son válidos", issues)


def _clean(value: str | None) -> str | None:
    return value.strip() if value is not None and value.strip() else None


def parse_official(
    upload: ExternalUpload, uris: Uris, settings: Settings, official_iri: str
) -> Graph:
    """El fichero oficial: se analiza (422 ``syntax``), declara ``<IRI oficial> a
    owl:Ontology`` (422 ``structure``) y no describe recursos bajo ``BASE_URI`` (422
    ``uri``). No se valida con las formas."""
    graph = ingest.parse_rdf(
        upload.data, upload.rdf_format, uris.base, max_triples=settings.ingest_max_triples
    )
    ingest.check_terms(graph)
    if (URIRef(official_iri), RDF.type, OWL.Ontology) not in graph:
        raise IngestError(
            "structure",
            f"El fichero no declara «<{official_iri}> a owl:Ontology»: tiene que ser la misma "
            "ontología externa",
            [Issue("Falta la declaración de la ontología", focus_node=official_iri)],
        )
    inside = sorted(
        {str(s) for s in graph.subjects() if isinstance(s, URIRef) and str(s).startswith(uris.base)}
    )
    if inside:
        raise IngestError(
            "uri",
            "El fichero oficial no puede describir recursos bajo BASE_URI",
            [Issue("Recurso bajo BASE_URI", focus_node=s) for s in inside[:50]],
        )
    return graph


# --- Registros ----------------------------------------------------------------------------


def build_records(
    uris: Uris, info: ExternalInfo, slug: str, upload: ExternalUpload, number: int, when: datetime
) -> tuple[Graph, Graph]:
    """``(referencia, versión)``: el registro de referencia nuevo de la externa (para
    ``{BASE_URI}onto/externas``) y el de la versión ``number``."""
    node = URIRef(info.uri)
    version = URIRef(uris.external_version(slug, number))
    version_info = _clean(upload.version_info)
    if version_info is not None and PLACEHOLDER.fullmatch(version_info):
        version_info = None

    reference = Graph()
    reference.add((node, RDF.type, OWL.Ontology))
    reference.add((node, DCT.title, Literal(upload.title.strip(), lang="es")))
    description = _clean(upload.description)
    if description is not None:
        reference.add((node, DCT.description, Literal(description, lang="es")))
    if version_info is not None:
        reference.add((node, OWL.versionInfo, Literal(version_info)))
    reference.add((node, VANN.preferredNamespacePrefix, Literal(upload.prefix)))
    reference.add((node, VANN.preferredNamespaceUri, URIRef(upload.namespace)))
    publisher = _clean(upload.publisher)
    if publisher is not None:
        agent = BNode()
        reference.add((node, DCT.publisher, agent))
        reference.add((agent, FOAF.name, Literal(publisher)))
    for n in range(1, number + 1):
        reference.add((node, DCAT.hasVersion, URIRef(uris.external_version(slug, n))))
    reference.add((node, DCAT.hasCurrentVersion, version))

    record = Graph()
    record.add((version, RDF.type, PROV.Entity))
    record.add((version, DCT.isVersionOf, node))
    record.add((version, DCAT.version, Literal(str(number))))
    if version_info is not None:
        record.add((version, OWL.versionInfo, Literal(version_info)))
    moment = when.astimezone(UTC).replace(microsecond=0)
    record.add((version, PROV.generatedAtTime, Literal(moment.isoformat(), datatype=XSD.dateTime)))
    if number > 1:
        previous = URIRef(uris.external_version(slug, number - 1))
        record.add((version, DCAT.previousVersion, previous))
        record.add((version, PROV.wasRevisionOf, previous))
    notes = _clean(upload.version_notes)
    if notes is not None:
        record.add((version, ADMS.versionNotes, Literal(notes, lang="es")))
    return reference, record


def validate_records(reference: Graph, record: Graph, uris: Uris, settings: Settings) -> None:
    """SHACL de la referencia y la versión juntas (``itsh:ExternalVersionShape`` e
    ``itsh:ExternalOntologyVersionedShape``), sin el fichero oficial."""
    ingest.validate_shacl(reference + record, settings.semantic_dir, uris.base, support=False)


# --- Métricas ---------------------------------------------------------------------------


def compute_external_metrics(
    graph: Graph, ontology_iri: str, namespace: str, settings: Settings
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Métricas OWL y consistencia del fichero oficial (decisión 51), como en las propias:
    sin descargar los ``owl:imports``. Cuentan como propias las entidades de
    ``namespace`` (el ``vann:preferredNamespaceUri`` de la referencia)."""
    metrics = owl_metrics.compute_metrics(graph, ontology_iri, namespace)
    consistency = owl_metrics.check_consistency(
        graph,
        ontology_iri,
        timeout_seconds=settings.reasoner_timeout_seconds,
        java_memory_mb=settings.reasoner_java_memory_mb,
    )
    return metrics.to_dict(), consistency.to_dict()


def _analyze(
    graph: Graph, ontology_iri: str, namespace: str, settings: Settings
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return compute_external_metrics(graph, ontology_iri, namespace, settings)
    except owl_metrics.OntologyLoadError as exc:
        issues = [Issue("Literal que no cumple su tipo de datos", value=v) for v in exc.values]
        raise IngestError("syntax", exc.message, issues) from None


# --- Sustitución --------------------------------------------------------------------------


@dataclass
class ReplaceResult:
    slug: str
    uri: str
    number: int
    version_uri: str
    previous_version: str | None
    triples: int
    generated_at: str
    metrics: dict[str, Any]
    consistency: dict[str, Any]


def _check_prefix(
    store: TripleStore, session: Session, uris: Uris, info: ExternalInfo, prefix: str
) -> None:
    """Reglas 7 y 14: el prefijo no es de un recurso dado de baja ni de otro recurso vivo
    (tampoco reservado por versiones anteriores de otra externa). El suyo actual o uno que
    la propia externa dejó de usar sí valen."""
    owner = vocab_ingest.withdrawn_prefix_owner(session, prefix)
    if owner is not None and owner != info.uri:
        raise IngestError(
            "prefix_withdrawn",
            f"El prefijo VANN «{prefix}» era de un recurso dado de baja y no se reutiliza",
            [
                Issue(
                    "Prefijo de un recurso dado de baja",
                    focus_node=info.uri,
                    path=str(VANN.preferredNamespacePrefix),
                    value=owner,
                )
            ],
        )
    owners = vocab_ingest.live_prefix_owners(store, uris, prefix, info.uri, session)
    if owners:
        raise IngestError(
            "prefix_in_use",
            f"El prefijo VANN «{prefix}» ya lo usa otro esquema u ontología: elige otro",
            [
                Issue(
                    "Prefijo de otro recurso",
                    focus_node=info.uri,
                    path=str(VANN.preferredNamespacePrefix),
                    value=other,
                )
                for other in owners
            ],
        )


def _tool_name() -> str:
    import owlready2

    version = getattr(owlready2, "VERSION", "?")
    return f"owlready2 {version}; {owl_metrics.REASONER_NAME} (incluido en owlready2)"


def replace_external(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    upload: ExternalUpload,
    actor: User | None = None,
    *,
    now: Any = None,
) -> ReplaceResult:
    """Sustituye entera la externa ``slug`` por una versión nueva (ver el docstring del
    módulo). ``now`` (función sin argumentos) solo lo cambian las pruebas."""
    clock = now or (lambda: datetime.now(UTC))
    info = find_external(reference_graph(store, uris), uris, slug)
    check_fields(upload)
    official = parse_official(upload, uris, settings, info.uri)
    # SHACL antes del bloqueo, con el n que toca ahora: un formulario inválido no espera.
    number = info.last + 1
    reference, record = build_records(uris, info, slug, upload, number, clock())
    validate_records(reference, record, uris, settings)
    metrics, consistency = _analyze(official, info.uri, upload.namespace, settings)
    digest = vocab_ingest.content_hash(official)

    with catalog_write_lock(session):
        store.ensure_writable()
        current = find_external(reference_graph(store, uris), uris, slug)
        if current.uri != info.uri:  # pragma: no cover - el slug no cambia de dueño
            raise ExternalNotFoundError(slug)
        number = current.last + 1
        reference, record = build_records(uris, current, slug, upload, number, clock())
        if current.versions != info.versions:
            validate_records(reference, record, uris, settings)
        _check_prefix(store, session, uris, current, upload.prefix)
        version_uri = uris.external_version(slug, number)
        if len(store.get_graph(version_uri)):
            if version_uri in current.versions.values() or version_uri == current.current:
                raise IngestError(
                    "version_exists",
                    f"La versión {number} ya existe: otra sustitución se ha adelantado",
                    [Issue("Versión ya publicada", focus_node=version_uri)],
                )
            # Grafo huérfano de una sustitución que falló a medias: ninguna referencia lo
            # lista ni lo muestra la API, así que se sobrescribe (reintento seguro).
            logger.warning("Se sobrescribe el grafo huérfano %s", version_uri)

        # 1. PostgreSQL: solo cuenta si la versión llega a la referencia.
        prefix_row = session.get(ExternalVersionPrefix, version_uri)
        if prefix_row is None:
            prefix_row = ExternalVersionPrefix(version_uri=version_uri)
            session.add(prefix_row)
        prefix_row.ontology_iri = current.uri
        prefix_row.prefix = upload.prefix
        prefix_row.created_at = datetime.now(UTC)
        metrics_row = session.get(OntologyMetricsRecord, version_uri)
        if metrics_row is None:
            metrics_row = OntologyMetricsRecord(version_iri=version_uri)
            session.add(metrics_row)
        metrics_row.ontology_iri = current.uri
        metrics_row.content_hash = digest
        metrics_row.metrics = metrics
        metrics_row.consistency = consistency
        metrics_row.tool = _tool_name()
        metrics_row.computed_at = datetime.now(UTC)
        session.commit()

        # 2. El grafo de la versión, y 3. la referencia en una sola petición de Update.
        content = official + record
        store.put_graph(version_uri, content)
        try:
            store.update(
                bajas.replace_subject_update(uris.external_ontologies_graph, current.uri, reference)
            )
        except TriplestoreError:
            try:
                store.delete_graph(version_uri)
            except TriplestoreError:
                logger.warning("No se ha podido borrar el grafo huérfano %s", version_uri)
            raise

        previous = uris.external_version(slug, number - 1) if number > 1 else None
        generated = str(record.value(URIRef(version_uri), PROV.generatedAtTime))
        audit.record(
            session,
            AuditAction.EXTERNAL_ONTOLOGY_REPLACED,
            actor=actor,
            details={
                "ontology": current.uri,
                "slug": slug,
                "version": str(number),
                "version_uri": version_uri,
                "graph": version_uri,
                "previous_version": previous,
                "prefix": upload.prefix,
                "triples": len(content),
                "consistent": consistency.get("consistent"),
                "via": "api",
            },
        )
        session.commit()
    return ReplaceResult(
        slug=slug,
        uri=current.uri,
        number=number,
        version_uri=version_uri,
        previous_version=previous,
        triples=len(content),
        generated_at=generated,
        metrics=metrics,
        consistency=consistency,
    )


# --- Lectura: ficha y RDF -----------------------------------------------------------------

# Registros de las versiones de una externa: solo los triples cuyo sujeto es la versión, en
# su propio grafo (el fichero oficial no se lee).
_VERSION_RECORDS = """CONSTRUCT { ?v ?p ?o } WHERE {
  GRAPH ?v { ?v ?p ?o }
  FILTER(STRSTARTS(STR(?v), $prefix))
}"""


def metrics_parts(m: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """Métricas guardadas -> campos ``metrics``, ``profile``, ``consistency`` y
    ``documentation`` de los esquemas de respuesta."""
    return {
        "metrics": schemas.OntologyMetricsRead(
            **{k: m[k] for k in schemas.OntologyMetricsRead.model_fields if k in m}
        ),
        "profile": schemas.OwlProfile(name=m["profile"], compatible=m["compatible_profiles"]),
        "consistency": schemas.ConsistencyRead(
            reasoner=c["reasoner"],
            consistent=c["consistent"],
            unsatisfiable_classes=c["unsatisfiable_classes"],
            unsatisfiable=c.get("unsatisfiable", []),
            detail=c.get("detail"),
        ),
        "documentation": schemas.DocumentationCoverageRead(**m["documentation"]),
    }


def _version_read(
    records: Graph, info: ExternalInfo, number: int, uri: str, metrics: dict[str, Any]
) -> schemas.ExternalVersionRead:
    node = URIRef(uri)
    previous = records.value(node, DCAT.previousVersion)
    record = metrics.get(uri)
    parts: dict[str, Any] = {
        "metrics": None,
        "profile": None,
        "consistency": None,
        "documentation": None,
    }
    if record is not None:
        parts = metrics_parts(record.metrics, record.consistency)
    return schemas.ExternalVersionRead(
        number=number,
        version=str(number),
        uri=uri,
        version_info=_literal(records, node, OWL.versionInfo),
        generated_at=_literal(records, node, PROV.generatedAtTime),
        previous_version=str(previous) if isinstance(previous, URIRef) else None,
        notes=pick_literal(records.objects(node, ADMS.versionNotes)),
        current=uri == info.current,
        metrics_computed_at=record.computed_at if record is not None else None,
        metrics_tool=record.tool if record is not None else None,
        **parts,
    )


def get_external(
    store: TripleStore, session: Session, uris: Uris, slug: str
) -> schemas.ExternalOntologyDetail:
    """Ficha de la externa ``slug``: referencia, versión actual y todas las versiones (solo
    las que lista ``dcat:hasVersion``; un grafo huérfano no aparece)."""
    graph = reference_graph(store, uris)
    info = find_external(graph, uris, slug)
    node = URIRef(info.uri)
    versions: list[schemas.ExternalVersionRead] = []
    if info.versions:
        records = store.construct(
            render(_VERSION_RECORDS, prefix=literal(f"{uris.external_series(slug)}/"))
        )
        metrics = vocabularies.metrics_records(session, list(info.versions.values()))
        versions = [
            _version_read(records, info, n, uri, metrics)
            for n, uri in sorted(info.versions.items(), reverse=True)
        ]
    publisher = graph.value(node, DCT.publisher)
    namespace = graph.value(node, VANN.preferredNamespaceUri)
    return schemas.ExternalOntologyDetail(
        slug=slug,
        uri=info.uri,
        kind="external",
        status="referenced",
        title=pick_literal(graph.objects(node, DCT.title)),
        description=pick_literal(graph.objects(node, DCT.description)),
        prefix=info.prefix,
        namespace=str(namespace) if isinstance(namespace, URIRef) else None,
        version=_literal(graph, node, OWL.versionInfo),
        publisher=(
            pick_literal(graph.objects(publisher, FOAF.name)) if publisher is not None else None
        ),
        current_version=next((v for v in versions if v.current), None),
        versions=versions,
    )


def version_rdf(store: TripleStore, uris: Uris, slug: str, number: int) -> Graph:
    """El grafo de la versión ``n`` (fichero oficial y registro). ``ExternalNotFoundError``
    si la externa no existe o no lista esa versión."""
    info = find_external(reference_graph(store, uris), uris, slug)
    uri = info.versions.get(number)
    if uri is None:
        raise ExternalNotFoundError(f"{slug}/{number}")
    return store.get_graph(uri)
