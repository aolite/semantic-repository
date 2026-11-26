"""CRUD de esquemas SKOS y ontologías propias en los catálogos (decisión 50).

Contrato: ``semantic/uris.md``, «Vocabularios y ontologías en los catálogos» (reglas 1 a
12). Mismos patrones que el CRUD de catálogos y datasets (``app.catalogs``, decisión 49):

- Publicar (``POST /schemes`` y ``POST /ontologies``, RDF) está en ``app.vocab_ingest``:
  el catálogo llega como parámetro y el triple «<catálogo> dcat:resource <recurso>» se
  valida con SHACL y se guarda en el grafo del catálogo.
- **Editar** (``PATCH``): de un esquema, sus metadatos (título, descripción, publicador) y
  su catálogo; de una ontología, solo su catálogo, porque sus metadatos están en cada
  versión y las versiones son inmutables (decisión 28). Mover es quitar el triple del
  catálogo de origen y añadirlo al de destino en una sola petición de Update.
- **Dar de baja** (``DELETE``): lápida en ``{BASE_URI}bajas`` (``itsh:BajaShape``), se
  borran el grafo del esquema (con sus conceptos) o los de todas las versiones de la
  ontología y el triple de su catálogo, y el prefijo VANN queda en PostgreSQL
  (``withdrawn_prefixes``) para que no se reutilice. 409 ``in_use`` si lo usan recursos
  vivos (regla 8 y usos validados el 2026-11-26). Sus conceptos y versiones responden
  410 por el prefijo de su URI. Robusta ante un fallo a medias (QA-50-04, ``_withdraw``):
  lo de Fuseki va en una sola petición de Update.
- Las ontologías externas y los esquemas auxiliares no se gestionan desde la aplicación
  (regla 5): 403 ``not_managed`` (propuesta de ``backend``, validada el 2026-11-26).

Toda operación va con el bloqueo de las escrituras del catálogo (``app.write_lock``).
"""

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import audit, bajas, catalogs, ingest, schemas, vocab_ingest, vocabularies
from app.catalog import NotFoundError
from app.catalogs import CrudError, catalog_or_error, locked, missing
from app.config import Settings
from app.ingest import IngestError, Issue
from app.models import AuditAction, OntologyMetricsRecord, User, WithdrawnPrefix
from app.sparql import iri, literal, render
from app.triplestore import TripleStore
from app.uris import DCAT, DCT, SKOS, Uris

LANG = "es"

MAPPING_RELATIONS = (
    SKOS.related,
    SKOS.exactMatch,
    SKOS.closeMatch,
    SKOS.broadMatch,
    SKOS.narrowMatch,
    SKOS.relatedMatch,
    DCT.isReplacedBy,
)

_PREFIXES = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# Usos de un esquema (regla 8): sus conceptos ($prefix = "{esquema}/") como dcat:theme de
# una versión de un dataset vivo, dct:subject de una versión de una ontología propia viva
# o destino de skos:related / *Match desde un concepto de otro esquema vivo. Lo vivo es lo
# que está en los grafos publicados (las bajas borran el grafo).
_THEME_USES = (
    _PREFIXES
    + """CONSTRUCT { ?v dcat:theme ?c . } WHERE {
  GRAPH ?s { ?s a dcat:DatasetSeries . ?v dcat:inSeries ?s ; dcat:theme ?c . }
  FILTER(STRSTARTS(STR(?s), $dataset_ns) && STRSTARTS(STR(?c), $prefix))
}"""
)
_SUBJECT_USES = (
    _PREFIXES
    + """CONSTRUCT { ?g dct:subject ?c . } WHERE {
  GRAPH ?g { ?o a owl:Ontology ; owl:versionIRI ?g ; dct:subject ?c . }
  FILTER(STRSTARTS(STR(?g), $onto_ns) && STRSTARTS(STR(?g), CONCAT(STR(?o), "/")))
  FILTER(?c = $scheme || STRSTARTS(STR(?c), $prefix))
}"""
)
# dct:isReplacedBy desde un concepto de otro esquema vivo (QA-50-02, validado el
# 2026-11-26): dar de baja el sustituto dejaría al otro esquema sin poder republicarse.
_MAPPING_USES = (
    _PREFIXES
    + """CONSTRUCT { ?x ?rel ?c . } WHERE {
  VALUES ?rel { skos:related skos:exactMatch skos:closeMatch skos:broadMatch
                skos:narrowMatch skos:relatedMatch dct:isReplacedBy }
  GRAPH ?g { ?g a skos:ConceptScheme . ?x skos:inScheme ?g ; ?rel ?c . }
  FILTER(STRSTARTS(STR(?g), $vocab_ns) && ?g != $scheme && STRSTARTS(STR(?c), $prefix))
}"""
)

# Usos de una ontología (regla 8): su URI o una versión ($own = "{ontología}/") como
# owl:imports de una versión de otra ontología propia viva, o un término suyo
# ($terms = "{ontología}#") en cualquier posición de una versión de otra ontología propia.
_IMPORT_USES = (
    _PREFIXES
    + """CONSTRUCT { ?g owl:imports ?t . } WHERE {
  GRAPH ?g { ?o a owl:Ontology ; owl:versionIRI ?g ; owl:imports ?t . }
  FILTER(STRSTARTS(STR(?g), $onto_ns) && STRSTARTS(STR(?g), CONCAT(STR(?o), "/")))
  FILTER(!STRSTARTS(STR(?g), $own))
  FILTER(?t = $onto || STRSTARTS(STR(?t), $own))
}"""
)
# dct:conformsTo de una versión de un dataset vivo hacia la ontología o una de sus
# versiones (validado el 2026-11-26).
_CONFORMS_USES = (
    _PREFIXES
    + """CONSTRUCT { ?v dct:conformsTo ?t . } WHERE {
  GRAPH ?s { ?s a dcat:DatasetSeries . ?v dcat:inSeries ?s ; dct:conformsTo ?t . }
  FILTER(STRSTARTS(STR(?s), $dataset_ns))
  FILTER(?t = $onto || STRSTARTS(STR(?t), $own))
}"""
)
_TERM_USES = (
    _PREFIXES
    + """CONSTRUCT { ?g dct:references ?t . } WHERE {
  GRAPH ?g {
    ?o a owl:Ontology ; owl:versionIRI ?g .
    { ?t ?p1 ?x1 } UNION { ?x2 ?t ?y2 } UNION { ?x3 ?p3 ?t }
  }
  FILTER(STRSTARTS(STR(?g), $onto_ns) && STRSTARTS(STR(?g), CONCAT(STR(?o), "/")))
  FILTER(!STRSTARTS(STR(?g), $own))
  FILTER(isIRI(?t) && STRSTARTS(STR(?t), $terms))
}"""
)


def _not_managed(what: str) -> CrudError:
    if what == "Una ontología externa":  # decisión 51: la única escritura es sustituirla
        detail = (
            f"{what} no se edita campo a campo, ni se da de baja, ni se cataloga: solo se "
            "sustituye entera (POST /ontologies/externas/{slug}/versions)"
        )
    else:
        detail = (
            f"{what} no se gestiona desde la aplicación: solo cambia con su fichero de "
            "semantic/ y load-semantic"
        )
    return CrudError(403, detail, kind="not_managed")


# --- Usos (regla 8) ---------------------------------------------------------------------


def scheme_uses(
    store: TripleStore, uris: Uris, scheme: str, concepts: set[URIRef]
) -> list[schemas.UsageRef]:
    prefix = literal(f"{scheme}/")
    uses: list[schemas.UsageRef] = []
    themes = store.construct(
        render(_THEME_USES, dataset_ns=literal(uris.dataset_ns), prefix=prefix)
    )
    for version, concept in themes.subject_objects(DCAT.theme):
        if concept in concepts:
            uses.append(
                schemas.UsageRef(
                    uri=str(version), resource="dataset", via=str(DCAT.theme), target=str(concept)
                )
            )
    subjects = store.construct(
        render(_SUBJECT_USES, onto_ns=literal(uris.onto_ns), scheme=iri(scheme), prefix=prefix)
    )
    for version, concept in subjects.subject_objects(DCT.subject):
        if concept in concepts or concept == URIRef(scheme):
            uses.append(
                schemas.UsageRef(
                    uri=str(version),
                    resource="ontology",
                    via=str(DCT.subject),
                    target=str(concept),
                )
            )
    mappings = store.construct(
        render(_MAPPING_USES, vocab_ns=literal(uris.vocab_ns), scheme=iri(scheme), prefix=prefix)
    )
    for relation in MAPPING_RELATIONS:
        for source, concept in mappings.subject_objects(relation):
            if concept in concepts:
                uses.append(
                    schemas.UsageRef(
                        uri=str(source), resource="scheme", via=str(relation), target=str(concept)
                    )
                )
    return sorted(uses, key=lambda u: (u.resource, u.uri, u.via or "", u.target))


def ontology_uses(store: TripleStore, uris: Uris, ontology: str) -> list[schemas.UsageRef]:
    own = literal(f"{ontology}/")
    uses: list[schemas.UsageRef] = []
    imports = store.construct(
        render(_IMPORT_USES, onto_ns=literal(uris.onto_ns), onto=iri(ontology), own=own)
    )
    for version, target in imports.subject_objects(OWL.imports):
        uses.append(
            schemas.UsageRef(
                uri=str(version), resource="ontology", via=str(OWL.imports), target=str(target)
            )
        )
    conforms = store.construct(
        render(_CONFORMS_USES, dataset_ns=literal(uris.dataset_ns), onto=iri(ontology), own=own)
    )
    for version, target in conforms.subject_objects(DCT.conformsTo):
        uses.append(
            schemas.UsageRef(
                uri=str(version), resource="dataset", via=str(DCT.conformsTo), target=str(target)
            )
        )
    terms = store.construct(
        render(
            _TERM_USES,
            onto_ns=literal(uris.onto_ns),
            own=own,
            terms=literal(f"{ontology}#"),
        )
    )
    for version, term in terms.subject_objects(DCT.references):
        uses.append(
            schemas.UsageRef(uri=str(version), resource="ontology", via=None, target=str(term))
        )
    return sorted(uses, key=lambda u: (u.resource, u.uri, u.via or "", u.target))


def _in_use(uses: list[schemas.UsageRef], what: str) -> CrudError:
    return CrudError(
        409,
        f"{what} lo usan recursos vivos: da de baja antes los que lo usan (las versiones "
        "publicadas son inmutables)",
        kind="in_use",
        used_by=uses,
    )


def _record_prefix(session: Session, prefix: str | None, resource: str) -> None:
    if prefix and session.get(WithdrawnPrefix, prefix) is None:
        session.add(WithdrawnPrefix(prefix=prefix, resource_uri=resource))


def _withdraw(
    store: TripleStore,
    session: Session,
    uris: Uris,
    uri: str,
    prefix: str | None,
    tombstone: Graph,
    graphs: list[str],
) -> None:
    """Baja robusta ante un fallo a medias (QA-50-04), en este orden:

    1. **PostgreSQL**: se reserva el prefijo VANN (``withdrawn_prefixes``) y se confirma.
       Si lo siguiente falla, el recurso sigue vivo y es el dueño del prefijo, así que
       puede seguir publicando (``check_resource_publication`` deja pasar a su dueño) y
       ningún otro recurso podía usarlo (QA-50-01). Un reintento no lo duplica.
    2. **Fuseki**, en **una** petición de Update (una transacción): lápida, pertenencia y
       grafos (``bajas.withdraw_resource_update``). O se aplica entera o no se aplica:
       nunca queda una lápida con el grafo vivo. Si falla, la baja se puede reintentar
       desde el principio.
    3. Lo que queda (auditoría y métricas) lo confirma quien llama. Si falla, la baja ya
       está hecha y es coherente; solo falta el evento de auditoría.
    """
    if prefix:
        _record_prefix(session, prefix, uri)
        session.commit()
    store.update(bajas.withdraw_resource_update(uris, uri, tombstone, graphs))


def _titles(graph: Graph, node: URIRef) -> list[Literal]:
    for prop in (DCT.title, SKOS.prefLabel):
        values = sorted((t for t in graph.objects(node, prop) if isinstance(t, Literal)), key=str)
        if values:
            return values
    return []


# --- Esquemas SKOS ----------------------------------------------------------------------


def _scheme_graph(
    store: TripleStore, uris: Uris, slug: str, corp: bool
) -> tuple[str, URIRef, Graph]:
    uri = uris.scheme(slug, corp=corp)
    if uris.is_auxiliary_scheme(uri):
        raise _not_managed("Un esquema auxiliar")
    graph = store.get_graph(uri)
    node = URIRef(uri)
    if (node, RDF.type, SKOS.ConceptScheme) not in graph:
        raise missing(store, uris, uri, "El esquema")
    return uri, node, graph


def _set_es(graph: Graph, node: URIRef, prop: URIRef, value: str) -> None:
    """Sustituye el literal en español (@es); los demás idiomas no cambian."""
    for old in list(graph.objects(node, prop)):
        if isinstance(old, Literal) and old.language == LANG:
            graph.remove((node, prop, old))
    graph.add((node, prop, Literal(value, lang=LANG)))


@locked
def update_scheme(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    corp: bool,
    data: schemas.SchemeUpdate,
    actor: User,
) -> str:
    store.ensure_writable()
    uri, node, graph = _scheme_graph(store, uris, slug, corp)
    current = bajas.resource_catalogs(store, uris, uri)
    if data.catalog is not None:
        target = catalog_or_error(store, uris, data.catalog, status_missing=422)
    elif current:
        target = sorted(current)[0]
    else:  # esquema sin catálogo (datos anteriores a la decisión 50): hay que indicarlo
        raise IngestError(
            "catalog",
            "El esquema no está en ningún catálogo: indica «catalog»",
            [Issue("Esquema sin catálogo", focus_node=uri)],
        )
    if data.title is not None:
        _set_es(graph, node, DCT.title, data.title)
        if any(True for _ in graph.objects(node, SKOS.prefLabel)):
            _set_es(graph, node, SKOS.prefLabel, data.title)
    if data.description is not None:
        _set_es(graph, node, DCT.description, data.description)
    catalogs.set_publisher(graph, node, data.publisher_name)
    graph.add((URIRef(target), DCAT.resource, node))
    # Misma validación que POST /schemes: estructura y SHACL con su triple de pertenencia.
    prepared = vocab_ingest.prepare_scheme(graph, uris, settings)
    _created, changed = ingest.store_graph(store, uri, prepared.graph)
    moved_from = sorted(bajas.set_resource_membership(store, uris, uri, target))
    audit.record(
        session,
        AuditAction.SCHEME_UPDATED,
        actor=actor,
        details={
            "scheme": uri,
            "fields": sorted(data.model_dump(exclude_unset=True)),
            "catalog": target,
            "moved_from": moved_from,
            "changed": changed or bool(moved_from),
            "via": "api",
        },
    )
    session.commit()
    return uri


@locked
def withdraw_scheme(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    corp: bool,
    actor: User,
) -> None:
    store.ensure_writable()
    uri, node, graph = _scheme_graph(store, uris, slug, corp)
    concepts = vocab_ingest.scheme_concepts(graph, uri)
    uses = scheme_uses(store, uris, uri, concepts)
    if uses:
        raise _in_use(uses, "El esquema")
    prefix = vocab_ingest.resource_prefix(graph, uri)
    tombstone = catalogs.build_tombstone(uris, uri, _titles(graph, node), settings)
    from_catalogs = sorted(bajas.resource_catalogs(store, uris, uri))
    _withdraw(store, session, uris, uri, prefix, tombstone, [uri])
    audit.record(
        session,
        AuditAction.SCHEME_WITHDRAWN,
        actor=actor,
        details={
            "scheme": uri,
            "slug": slug,
            "corp": corp,
            "catalogs": from_catalogs,
            "concepts": len(concepts),
            "prefix": prefix,
            "via": "api",
        },
    )
    session.commit()


# --- Ontologías propias -----------------------------------------------------------------


def _versions(store: TripleStore, uris: Uris, slug: str) -> vocabularies.OntologyVersions:
    if uris.ontology_slug(uris.ontology(slug)) is None:  # «externas»: las externas
        raise _not_managed("Una ontología externa")
    try:
        return vocabularies.load_versions(store, uris, slug)
    except NotFoundError:
        raise missing(store, uris, uris.ontology(slug), "La ontología") from None


@locked
def update_ontology(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    data: schemas.OntologyUpdate,
    actor: User,
) -> str:
    store.ensure_writable()
    versions = _versions(store, uris, slug)
    target = catalog_or_error(store, uris, data.catalog, status_missing=422)
    current = versions.current()
    assert current is not None  # noqa: S101 - load_versions garantiza al menos una
    # La versión actual con el triple de destino tiene que seguir cumpliendo las formas
    # (itsh:OwnOntology-catalog). No se calculan métricas: la versión no cambia.
    graph = vocabularies.version_graph(store, str(current))
    graph.add((URIRef(target), DCAT.resource, URIRef(versions.uri)))
    vocab_ingest.prepare_ontology(graph, uris, settings)
    moved_from = sorted(bajas.set_resource_membership(store, uris, versions.uri, target))
    audit.record(
        session,
        AuditAction.ONTOLOGY_UPDATED,
        actor=actor,
        details={
            "ontology": versions.uri,
            "fields": sorted(data.model_dump(exclude_unset=True)),
            "catalog": target,
            "moved_from": moved_from,
            "changed": bool(moved_from),
            "via": "api",
        },
    )
    session.commit()
    return versions.uri


@locked
def withdraw_ontology(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    actor: User,
) -> None:
    store.ensure_writable()
    versions = _versions(store, uris, slug)
    uri = versions.uri
    uses = ontology_uses(store, uris, uri)
    if uses:
        raise _in_use(uses, "La ontología")
    current = versions.current()
    assert current is not None  # noqa: S101 - load_versions garantiza al menos una
    header = vocabularies.version_graph(store, str(current))
    node = URIRef(uri)
    prefix = vocab_ingest.resource_prefix(header, uri)
    # Su dct:title es el de la última versión (semantic/uris.md).
    tombstone = catalogs.build_tombstone(uris, uri, _titles(header, node), settings)
    from_catalogs = sorted(bajas.resource_catalogs(store, uris, uri))
    version_iris = sorted(str(n) for n in versions.nodes())
    _withdraw(store, session, uris, uri, prefix, tombstone, version_iris)
    # Métricas de versiones que ya no existen: datos derivados, se borran (después de la
    # baja en Fuseki: si esta falla, la ontología sigue viva con sus métricas).
    session.execute(
        delete(OntologyMetricsRecord).where(OntologyMetricsRecord.version_iri.in_(version_iris))
    )
    audit.record(
        session,
        AuditAction.ONTOLOGY_WITHDRAWN,
        actor=actor,
        details={
            "ontology": uri,
            "slug": slug,
            "catalogs": from_catalogs,
            "versions": [versions.version_of(URIRef(v)) for v in version_iris],
            "prefix": prefix,
            "via": "api",
        },
    )
    session.commit()
