"""CRUD de catálogos y datasets (decisión 49).

Los formularios llegan como JSON (``app.schemas``); aquí se convierten a RDF, se validan
con **todas** las formas SHACL (como cualquier ingesta) y se escriben en el triplestore.

- Catálogo ``{BASE_URI}catalogo/{slug}``: grafo con nombre igual a su URI, con
  ``dct:title``, ``dct:description``, ``dct:publisher`` y un ``dcat:dataset`` por serie. Al
  crearlo se añade ``<{BASE_URI}catalogo> dcat:catalog <catálogo>`` al raíz; al darlo de
  baja se quita. El raíz no se toca de otra forma.
- Dataset (serie): se crea sin versiones en un catálogo; sus metadatos de serie se editan
  (también el catálogo: moverlo); las versiones siguen publicándose con ``POST /datasets``
  y son inmutables (decisión 28).
- Baja (borrado lógico): el grafo del recurso se borra, el enlace desde su catálogo (o
  desde el raíz) se quita, sus ficheros se eliminan y queda una lápida en
  ``{BASE_URI}bajas``. Quién la dio de baja va a la auditoría, no al RDF.
- Un slug dado de baja no se reutiliza (409) y un catálogo con datasets no se puede dar de
  baja (409).
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit, bajas, catalog, ingest, schemas
from app.config import Settings
from app.models import AuditAction, DistributionFile, FairEvaluation, User
from app.storage import Storage, StorageError
from app.triplestore import TripleStore
from app.uris import DCAT, DCT, FOAF, PROV, Uris

logger = logging.getLogger(__name__)

LANG = "es"


@dataclass
class CrudError(Exception):
    """Error de una operación del CRUD con su código HTTP."""

    status_code: int
    detail: str
    tombstone: bajas.Tombstone | None = None
    datasets: list[str] = field(default_factory=list)
    kind: str | None = None  # 409: schemas.ConflictKind

    def __str__(self) -> str:
        return self.detail


def _missing(store: TripleStore, uris: Uris, uri: str, what: str) -> CrudError:
    """404, o 410 con la lápida si el recurso se dio de baja."""
    tombstone = bajas.get_tombstone(store, uris, uri)
    if tombstone is not None:
        return CrudError(410, f"{what} se dio de baja", tombstone=tombstone)
    return CrudError(404, f"{what} no existe")


def _check_slug_free(store: TripleStore, uris: Uris, uri: str, exists: bool, what: str) -> None:
    if bajas.get_tombstone(store, uris, uri) is not None:
        raise CrudError(
            409, f"{what} con ese slug se dio de baja: el slug no se reutiliza", kind="withdrawn"
        )
    if exists:
        raise CrudError(409, f"Ya existe {what.lower()} con ese slug", kind="slug_in_use")


def _set_text(graph: Graph, node: URIRef, prop: URIRef, value: str | None) -> None:
    if value is None:
        return
    graph.remove((node, prop, None))
    graph.add((node, prop, Literal(value, lang=LANG)))


def _remove_node(graph: Graph, node: Any) -> None:
    """Quita un nodo en blanco y sus triples (el publicador anterior)."""
    if isinstance(node, BNode) and not any(True for _ in graph.subjects(None, node)):
        graph.remove((node, None, None))


def _set_publisher(graph: Graph, node: URIRef, name: str | None) -> None:
    if name is None:
        return
    previous = list(graph.objects(node, DCT.publisher))
    graph.remove((node, DCT.publisher, None))
    for old in previous:
        _remove_node(graph, old)
    agent = BNode()
    graph.add((node, DCT.publisher, agent))
    graph.add((agent, RDF.type, FOAF.Agent))
    graph.add((agent, RDF.type, PROV.Agent))
    graph.add((agent, FOAF.name, Literal(name)))


def _validate_catalog(graph: Graph, uris: Uris, uri: str, settings: Settings) -> None:
    ingest.check_catalog_structure(graph, uris, uri)
    ingest.validate_plain(graph, settings.semantic_dir, uris.base)


def _tombstone(
    store: TripleStore, uris: Uris, uri: str, titles: list[Literal], settings: Settings
) -> Graph:
    # Solo el catálogo y la serie tienen lápida (semantic/uris.md), con título no vacío.
    if uris.catalog_slug(uri) is None and uris.series_slug(uri) is None:
        raise ValueError(f"Solo un catálogo o una serie pueden darse de baja: {uri}")
    titles = [t for t in titles if str(t).strip()]
    graph = bajas.tombstone_graph(uri, titles or [Literal(uri)])
    ingest.validate_plain(graph, settings.semantic_dir, uris.base)  # forma itsh:BajaShape
    bajas.add_tombstone(store, uris, graph)
    return graph


# --- Catálogos --------------------------------------------------------------------------


def create_catalog(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    data: schemas.CatalogCreate,
    actor: User,
) -> str:
    uri = uris.catalog(data.slug)
    store.ensure_writable()
    _check_slug_free(store, uris, uri, bajas.catalog_exists(store, uri), "El catálogo")
    node = URIRef(uri)
    graph = Graph()
    graph.add((node, RDF.type, DCAT.Catalog))
    _set_text(graph, node, DCT.title, data.title)
    _set_text(graph, node, DCT.description, data.description)
    _set_publisher(graph, node, data.publisher_name)
    _validate_catalog(graph, uris, uri, settings)
    store.put_graph(uri, graph)
    bajas.add_to_root(store, uris, uri)
    audit.record(
        session,
        AuditAction.CATALOG_CREATED,
        actor=actor,
        details={"catalog": uri, "slug": data.slug, "via": "api"},
    )
    session.commit()
    return uri


def update_catalog(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    data: schemas.CatalogUpdate,
    actor: User,
) -> str:
    uri = uris.catalog(slug)
    store.ensure_writable()
    graph = store.get_graph(uri)
    node = URIRef(uri)
    if (node, RDF.type, DCAT.Catalog) not in graph:
        raise _missing(store, uris, uri, "El catálogo")
    _set_text(graph, node, DCT.title, data.title)
    _set_text(graph, node, DCT.description, data.description)
    _set_publisher(graph, node, data.publisher_name)
    _validate_catalog(graph, uris, uri, settings)
    _created, changed = ingest.store_graph(store, uri, graph)
    audit.record(
        session,
        AuditAction.CATALOG_UPDATED,
        actor=actor,
        details={
            "catalog": uri,
            "fields": sorted(data.model_dump(exclude_unset=True)),
            "changed": changed,
            "via": "api",
        },
    )
    session.commit()
    return uri


def withdraw_catalog(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    actor: User,
) -> None:
    uri = uris.catalog(slug)
    store.ensure_writable()
    graph = store.get_graph(uri)
    node = URIRef(uri)
    if (node, RDF.type, DCAT.Catalog) not in graph:
        raise _missing(store, uris, uri, "El catálogo")
    datasets = sorted(str(d) for d in graph.objects(node, DCAT.dataset))
    if datasets:
        raise CrudError(
            409,
            "El catálogo tiene datasets: muévelos a otro catálogo o dalos de baja antes",
            datasets=datasets,
            kind="catalog_not_empty",
        )
    titles = sorted((t for t in graph.objects(node, DCT.title) if isinstance(t, Literal)), key=str)
    _tombstone(store, uris, uri, titles, settings)
    bajas.remove_from_root(store, uris, uri)
    store.delete_graph(uri)
    audit.record(
        session,
        AuditAction.CATALOG_WITHDRAWN,
        actor=actor,
        details={"catalog": uri, "slug": slug, "via": "api"},
    )
    session.commit()


# --- Datasets (series) ------------------------------------------------------------------


def _catalog_or_error(store: TripleStore, uris: Uris, slug: str, *, status_missing: int) -> str:
    """URI del catálogo ``slug`` si existe. Si no, ``status_missing`` (404 en la ruta del
    catálogo, 422 en un campo del cuerpo) o 410/422 si está dado de baja."""
    uri = uris.catalog(slug)
    if bajas.catalog_exists(store, uri):
        return uri
    gone = bajas.get_tombstone(store, uris, uri)
    if status_missing == 404:
        if gone is not None:
            raise CrudError(410, "El catálogo se dio de baja", tombstone=gone)
        raise CrudError(404, "El catálogo no existe")
    detail = "El catálogo de destino se dio de baja" if gone else "El catálogo de destino no existe"
    raise ingest.IngestError(
        "catalog", detail, [ingest.Issue("Catálogo de destino", focus_node=uri)]
    )


def create_series(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    catalog_slug: str,
    data: schemas.DatasetCreate,
    actor: User,
) -> str:
    store.ensure_writable()
    catalog_uri = _catalog_or_error(store, uris, catalog_slug, status_missing=404)
    uri = uris.series(data.slug)
    _check_slug_free(store, uris, uri, len(store.get_graph(uri)) > 0, "El dataset")
    node = URIRef(uri)
    graph = Graph()
    graph.add((node, RDF.type, DCAT.DatasetSeries))
    _set_text(graph, node, DCT.title, data.title)
    _set_text(graph, node, DCT.description, data.description)
    _set_publisher(graph, node, data.publisher_name)
    graph.add((URIRef(catalog_uri), DCAT.dataset, node))
    prepared = ingest.prepare_series(graph, uris, settings.semantic_dir)
    ingest.publish(store, prepared)
    audit.record(
        session,
        AuditAction.DATASET_CREATED,
        actor=actor,
        details={"series": uri, "slug": data.slug, "catalog": catalog_uri, "via": "api"},
    )
    session.commit()
    return uri


def update_series(
    store: TripleStore,
    session: Session,
    uris: Uris,
    settings: Settings,
    slug: str,
    data: schemas.DatasetUpdate,
    actor: User,
) -> str:
    uri = uris.series(slug)
    node = URIRef(uri)
    store.ensure_writable()
    graph = catalog.series_graph(store, uris, slug)
    if (node, RDF.type, DCAT.DatasetSeries) not in graph:
        raise _missing(store, uris, uri, "El dataset")
    current_catalogs = bajas.series_catalogs(store, uris, uri)
    if data.catalog is not None:
        target = _catalog_or_error(store, uris, data.catalog, status_missing=422)
    elif current_catalogs:
        target = sorted(current_catalogs)[0]
    else:  # serie sin catálogo (datos anteriores a la decisión 49): hay que indicarlo
        raise ingest.IngestError(
            "catalog",
            "El dataset no está en ningún catálogo: indica «catalog»",
            [ingest.Issue("Serie sin catálogo", focus_node=uri)],
        )
    _set_text(graph, node, DCT.title, data.title)
    _set_text(graph, node, DCT.description, data.description)
    _set_publisher(graph, node, data.publisher_name)
    graph.add((URIRef(target), DCAT.dataset, node))
    # Misma validación que POST /datasets: estructura y SHACL de la serie completa (con
    # sus versiones, que no cambian) y su triple de pertenencia.
    prepared = ingest.prepare_series(graph, uris, settings.semantic_dir)
    _created, changed = ingest.store_graph(store, uri, prepared.graph)
    moved_from = sorted(bajas.set_membership(store, uris, uri, target))
    audit.record(
        session,
        AuditAction.DATASET_UPDATED,
        actor=actor,
        details={
            "series": uri,
            "fields": sorted(data.model_dump(exclude_unset=True)),
            "catalog": target,
            "moved_from": moved_from,
            "changed": changed or bool(moved_from),
            "via": "api",
        },
    )
    session.commit()
    return uri


def withdraw_series(
    store: TripleStore,
    session: Session,
    storage: Storage,
    uris: Uris,
    settings: Settings,
    slug: str,
    actor: User,
) -> None:
    uri = uris.series(slug)
    node = URIRef(uri)
    store.ensure_writable()
    graph = catalog.series_graph(store, uris, slug)
    if (node, RDF.type, DCAT.DatasetSeries) not in graph:
        raise _missing(store, uris, uri, "El dataset")
    titles = sorted((t for t in graph.objects(node, DCT.title) if isinstance(t, Literal)), key=str)
    versions = sorted(ingest.published_versions(graph, uri))
    _tombstone(store, uris, uri, titles, settings)
    catalogs = sorted(bajas.series_catalogs(store, uris, uri))
    for catalog_uri in catalogs:
        bajas.remove_membership(store, catalog_uri, uri)
    store.delete_graph(uri)

    # Ficheros de distribución (clave {slug}/{version}/{dist}): se eliminan.
    deleted: list[str] = []
    failed: list[str] = []
    rows = session.scalars(
        select(DistributionFile).where(DistributionFile.storage_key.startswith(f"{slug}/"))
    ).all()
    for row in rows:
        try:
            storage.delete(row.storage_key)
        except StorageError:
            logger.warning("No se ha podido borrar el fichero %s", row.storage_key)
            failed.append(row.storage_key)
            continue
        deleted.append(row.storage_key)
        session.delete(row)
    # Evaluaciones FAIR pendientes de versiones que ya no existen.
    session.execute(
        update(FairEvaluation)
        .where(
            FairEvaluation.version_uri.startswith(f"{uri}/"),
            FairEvaluation.status == "pending",
        )
        .values(status="failed", error="Dataset dado de baja")
    )
    audit.record(
        session,
        AuditAction.DATASET_WITHDRAWN,
        actor=actor,
        details={
            "series": uri,
            "slug": slug,
            "catalogs": catalogs,
            "versions": versions,
            "files_deleted": sorted(deleted),
            "files_not_deleted": sorted(failed),
            "via": "api",
        },
    )
    session.commit()


# --- 410 por prefijo --------------------------------------------------------------------


def gone_response(tombstone: bajas.Tombstone, uris: Uris) -> schemas.GoneResponse:
    resource = "catalog" if uris.catalog_slug(tombstone.uri) is not None else "dataset"
    return schemas.GoneResponse(
        detail="Recurso dado de baja",
        uri=tombstone.uri,
        resource=resource,
        title=tombstone.title,
        withdrawn_at=tombstone.withdrawn_at,
    )


def series_tombstone(store: TripleStore, uris: Uris, slug: str) -> bajas.Tombstone | None:
    """Lápida de la serie ``slug``: vale para sus versiones, distribuciones y ficheros,
    que se resuelven por el prefijo ``{BASE_URI}dataset/{slug}/``."""
    return bajas.get_tombstone(store, uris, uris.series(slug))
