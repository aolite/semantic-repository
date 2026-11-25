"""CLI de administración del backend.

Uso::

    uv run python -m app.cli create-admin --username <nombre>
    uv run python -m app.cli load-semantic
    printf '%s' "$PASSWORD" | uv run python -m app.cli create-admin --username <nombre> \
        --password-stdin

La contraseña nunca se pasa como argumento (quedaría en el historial y en ``ps``):
se pide de forma interactiva, oculta y con confirmación, o se lee de stdin.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from rdflib import Graph, URIRef
from rdflib.compare import isomorphic
from sqlalchemy.orm import Session

from app import bajas, distributions, ingest, vocab_ingest, write_lock
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.models import DistributionFile, Role
from app.schemas import USERNAME_PATTERN
from app.security import PASSWORD_MIN_LENGTH
from app.storage import Storage, StorageError, hash_stream, storage_from_settings
from app.triplestore import FusekiStore, MemoryStore, TripleStore, TriplestoreError
from app.uris import CORP_SEGMENT, DCAT, DCT, Uris, is_slug, is_version
from app.users import UsernameTakenError, create_user

cli = typer.Typer(help="Administración del backend del repositorio semántico IT&OT.")

CLI_ACTOR = "cli"


@cli.callback()
def main() -> None:
    """Comandos de administración."""


def _read_password(password_stdin: bool) -> str:
    if password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    return typer.prompt("Contraseña", hide_input=True, confirmation_prompt=True)


@cli.command("create-admin")
def create_admin(
    username: Annotated[str, typer.Option(help="Nombre de usuario del admin")],
    password_stdin: Annotated[
        bool,
        typer.Option("--password-stdin", help="Lee la contraseña de la primera línea de stdin"),
    ] = False,
) -> None:
    """Crea una cuenta con rol admin. Pensado para el primer admin de la unidad."""
    if not re.fullmatch(USERNAME_PATTERN, username):
        typer.echo(
            "Nombre de usuario no válido: de 3 a 64 caracteres, "
            "minúsculas, dígitos, '.', '-' o '_'.",
            err=True,
        )
        raise typer.Exit(code=2)

    password = _read_password(password_stdin)
    if len(password) < PASSWORD_MIN_LENGTH:
        typer.echo(f"La contraseña debe tener al menos {PASSWORD_MIN_LENGTH} caracteres.", err=True)
        raise typer.Exit(code=2)

    session = get_sessionmaker()()
    try:
        create_user(
            session,
            username=username,
            password=password,
            role=Role.ADMIN,
            actor_username=CLI_ACTOR,
            via="cli",
        )
    except UsernameTakenError:
        typer.echo(f"Ya existe una cuenta con el nombre '{username}'.", err=True)
        raise typer.Exit(code=1) from None
    finally:
        session.close()

    typer.echo(f"Admin '{username}' creado.")


def get_store(settings: Settings) -> TripleStore:
    return FusekiStore.from_settings(settings)


def _print_ingest_error(name: str, exc: ingest.IngestError) -> None:
    typer.echo(f"  {name}: {exc.detail}", err=True)
    for issue in exc.issues:
        where = f" [{issue.focus_node}]" if issue.focus_node else ""
        path = f" ({issue.path})" if issue.path else ""
        typer.echo(f"    - {issue.message}{where}{path}", err=True)


@dataclass
class _Plan:
    """Todo lo que ``load-semantic`` va a escribir, ya validado."""

    schemes: list[tuple[str, vocab_ingest.PreparedScheme]] = field(default_factory=list)
    # Decisión 50: por esquema, el grafo del fichero (sin los conceptos publicados desde la
    # aplicación ni el triple de pertenencia) y sus catálogos, para volver a mezclarlo con
    # lo publicado justo antes de escribir.
    scheme_sources: dict[str, tuple[Graph, list[str]]] = field(default_factory=dict)
    ontologies: list[tuple[str, vocab_ingest.PreparedOntology, vocab_ingest.OntologyAnalysis]] = (
        field(default_factory=list)
    )
    plain: list[tuple[str, str, Graph]] = field(default_factory=list)
    # Catálogo raíz y catálogos de data/catalogos/ (decisión 49).
    catalogs: list[tuple[str, str, Graph]] = field(default_factory=list)
    series: list[tuple[str, ingest.PreparedSeries]] = field(default_factory=list)
    # URIs con lápida en el grafo de bajas: sus ficheros se omiten.
    withdrawn: set[str] = field(default_factory=set)
    files: list[tuple[str, Path, tuple[str, str, str]]] = field(default_factory=list)


FILES_DIR = ingest.SYNTHETIC_DIR / "ficheros"


def get_file_storage(settings: Settings) -> Storage:
    return storage_from_settings(settings)


def _file_paths(semantic_dir: Path) -> list[Path]:
    root = semantic_dir / FILES_DIR
    return sorted(p for p in root.glob("*/*/*") if p.is_file()) if root.is_dir() else []


def _check_files(
    semantic_dir: Path, settings: Settings, uris: Uris, session: Session, plan: _Plan
) -> bool:
    """Ficheros de ``data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}``, validados con
    las mismas reglas que ``PUT …/file``: la distribución existe en las series que se van a
    cargar, no es NON_PUBLIC, cabe en ``MAX_UPLOAD_MB`` y, si ya se subió, tiene el mismo
    SHA-256. Que falte el fichero de una distribución no es un error (queda
    ``download: unavailable``)."""
    graphs = {prepared.slug: prepared.graph for _name, prepared in plan.series}
    failed = False
    withdrawn_slugs = {
        slug for uri in plan.withdrawn if (slug := uris.series_slug(uri)) is not None
    }
    seen: set[str] = set()
    limit = settings.max_upload_mb * 1024 * 1024
    for path in _file_paths(semantic_dir):
        name = str(path.relative_to(semantic_dir))
        slug, version, dist = path.parent.parent.name, path.parent.name, path.stem
        if slug in withdrawn_slugs:
            typer.echo(f"  {name}: se omite (dataset dado de baja)")
            continue
        problem = None
        if not (is_slug(slug) and is_version(version) and is_slug(dist)) or path.suffix == "":
            problem = "la ruta debe ser {slug}/{version}/{dist}.{ext}"
        elif f"{slug}/{version}/{dist}" in seen:
            problem = "hay más de un fichero para la misma distribución"
        elif path.stat().st_size > limit:
            problem = f"supera MAX_UPLOAD_MB ({settings.max_upload_mb} MB)"
        else:
            graph = graphs.get(slug)
            version_node = URIRef(uris.version(slug, version))
            dist_node = URIRef(f"{uris.version(slug, version)}/{dist}")
            if graph is None or (version_node, DCAT.distribution, dist_node) not in graph:
                problem = "la distribución no está descrita en data/sintetico/"
            else:
                rights = graph.value(dist_node, DCT.accessRights) or graph.value(
                    version_node, DCT.accessRights
                )
                if distributions.access_code(rights) == "NON_PUBLIC":
                    problem = "la distribución es NON_PUBLIC (solo metadatos): no admite fichero"
        key = f"{slug}/{version}/{dist}"
        if problem is None:
            record = session.get(DistributionFile, key)
            if record is not None:
                with path.open("rb") as handle:
                    if hash_stream(handle).sha256 != record.sha256:
                        problem = "ya hay un fichero subido con otro contenido (inmutable)"
        if problem is not None:
            typer.echo(f"  {name}: {problem}", err=True)
            failed = True
            continue
        seen.add(key)
        plan.files.append((name, path, (slug, version, dist)))
    return failed


def _known_concepts(plan: _Plan) -> set[str]:
    return {
        str(c)
        for _name, prepared in plan.schemes
        for c in vocab_ingest.scheme_concepts(prepared.graph, prepared.uri)
    }


def _write_schemes_and_ontologies(
    store: TripleStore, session: Session, settings: Settings, uris: Uris, plan: _Plan
) -> None:
    """Esquemas, externas y versiones de ontología. Las métricas y el razonador ya se
    calcularon al validar. Decisión 50: cada esquema se vuelve a mezclar con lo publicado
    justo antes de escribirlo (los conceptos añadidos desde la aplicación no se quitan) y
    cada recurso queda en su catálogo (el que ya tenía, o el de ``data/catalogos/``)."""
    known = _known_concepts(plan)
    for name, scheme in plan.schemes:
        source = plan.scheme_sources.get(scheme.uri)
        if source is not None:
            file_graph, catalogs = source
            merged = vocab_ingest.merge_published_concepts(
                store.get_graph(scheme.uri), file_graph, scheme.uri
            )
            if not isomorphic(merged, scheme.graph):
                # Lo publicado cambió mientras se validaba: se valida otra vez la mezcla.
                scheme = vocab_ingest.prepare_scheme(
                    _with_membership(merged, scheme.uri, catalogs), uris, settings
                )
        result = vocab_ingest.publish_scheme_and_audit(
            store,
            session,
            scheme,
            actor_username=CLI_ACTOR,
            via="cli",
            other="keep",
            check_concepts=False,
            known_concepts=known,
        )
        state = "cargado" if result.changed else "sin cambios"
        typer.echo(f"{name} -> <{result.graph_uri}>: {state} ({result.concepts} conceptos)")
    for name, graph_uri, graph in plan.plain:
        _created, changed = ingest.store_graph(store, graph_uri, graph)
        typer.echo(f"{name} -> <{graph_uri}>: {'cargado' if changed else 'sin cambios'}")
    for name, ontology, analysis in plan.ontologies:
        onto = vocab_ingest.publish_ontology_and_audit(
            store,
            session,
            ontology,
            settings,
            analysis=analysis,
            actor_username=CLI_ACTOR,
            via="cli",
            other="keep",
        )
        state = "cargado" if onto.changed else "sin cambios"
        metrics = "métricas calculadas" if onto.metrics_recomputed else "métricas al día"
        typer.echo(f"{name} -> <{onto.graph_uri}>: {state}, {metrics}")


def _write_catalogs(store: TripleStore, uris: Uris, plan: _Plan) -> None:
    for name, graph_uri, graph in plan.catalogs:
        # Decisión 49: se conservan los dcat:catalog del raíz y los dcat:dataset de cada
        # catálogo que ya están publicados (lo hecho desde la aplicación).
        current = store.get_graph(graph_uri)
        if graph_uri == uris.root_catalog:
            graph = ingest.merge_root_catalog(current, graph, uris, plan.withdrawn)
        else:
            graph = ingest.merge_catalog(current, graph, graph_uri)
        _created, changed = ingest.store_graph(store, graph_uri, graph)
        typer.echo(f"{name} -> <{graph_uri}>: {'cargado' if changed else 'sin cambios'}")


def _write_series_and_files(
    store: TripleStore, session: Session, settings: Settings, uris: Uris, plan: _Plan
) -> None:
    for name, series in plan.series:
        published = ingest.publish_and_audit(
            store, session, series, actor_username=CLI_ACTOR, via="cli", other="keep"
        )
        state = "cargado" if published.changed else "sin cambios"
        fair_note = (
            f"; evaluación FAIR encolada para {len(published.new_versions)}"
            if published.new_versions
            else ""
        )
        typer.echo(
            f"{name} -> <{published.graph_uri}>: {state} "
            f"(versiones {', '.join(published.versions) or '-'}{fair_note})"
        )
    if plan.files:
        file_storage = get_file_storage(settings)
        for name, path, (slug, version, dist) in plan.files:
            info = distributions.lookup(store, uris, slug, version, dist)
            with path.open("rb") as handle:
                uploaded = distributions.upload(
                    session,
                    file_storage,
                    info,
                    handle,
                    actor_username=CLI_ACTOR,
                    via="cli",
                )
            state = "subido" if uploaded.created else "sin cambios"
            typer.echo(f"{name} -> {info.storage_key}: {state}")


def _skip_withdrawn_meanwhile(store: TripleStore, uris: Uris, plan: _Plan) -> None:
    """Quita del plan lo que se dio de baja desde la aplicación después de validar."""
    fresh = bajas.withdrawn_uris(store, uris) - plan.withdrawn
    if not fresh:
        return
    plan.withdrawn |= fresh
    for name, graph_uri, _graph in plan.catalogs:
        if graph_uri in fresh:
            typer.echo(f"  {name}: se omite (catálogo dado de baja)")
    plan.catalogs = [entry for entry in plan.catalogs if entry[1] not in fresh]
    for name, prepared in plan.series:
        if prepared.uri in fresh:
            typer.echo(f"  {name}: se omite (dataset dado de baja)")
    plan.series = [entry for entry in plan.series if entry[1].uri not in fresh]
    slugs = {slug for uri in fresh if (slug := uris.series_slug(uri)) is not None}
    plan.files = [entry for entry in plan.files if entry[2][0] not in slugs]
    # Decisión 50: esquemas y ontologías dados de baja mientras se validaba.
    for name, scheme in plan.schemes:
        if scheme.uri in fresh:
            typer.echo(f"  {name}: se omite (esquema dado de baja)")
    plan.schemes = [entry for entry in plan.schemes if entry[1].uri not in fresh]
    for name, ontology, _analysis in plan.ontologies:
        if ontology.uri in fresh:
            typer.echo(f"  {name}: se omite (ontología dada de baja)")
    plan.ontologies = [entry for entry in plan.ontologies if entry[1].uri not in fresh]


def _catalog_paths(semantic_dir: Path) -> list[Path]:
    root = semantic_dir / ingest.CATALOGS_DIR
    return sorted(root.glob("*.ttl")) if root.is_dir() else []


def _check_series_catalog(
    store: TripleStore, uris: Uris, prepared: ingest.PreparedSeries, loaded: set[str]
) -> None:
    """Antes de escribir: una serie que ya está en un catálogo se queda en él (un traslado
    hecho desde la aplicación no se deshace); una serie nueva necesita que su catálogo se
    cargue en esta misma ejecución o ya esté publicado."""
    if bajas.series_catalogs(store, uris, prepared.uri):
        return
    target = prepared.catalog_uri
    if target is None or target in loaded or bajas.catalog_exists(store, target):
        return
    raise ingest.IngestError(
        "catalog",
        "El catálogo de la serie no existe, está dado de baja o no está en data/catalogos/",
        [ingest.Issue("Catálogo de la serie", focus_node=target)],
    )


def _file_memberships(semantic_dir: Path, uris: Uris) -> dict[str, list[str]]:
    """Decisión 50: catálogos que da ``data/catalogos/`` a cada esquema u ontología
    (``<catálogo> dcat:resource <recurso>``). Un fichero que no se puede leer se ignora
    aquí: lo informa la validación de los catálogos."""
    result: dict[str, list[str]] = {}
    for path in _catalog_paths(semantic_dir):
        if not is_slug(path.stem):
            continue
        catalog_uri = uris.catalog(path.stem)
        try:
            graph = ingest.parse_file(path, uris.base)
        except ingest.IngestError:
            continue
        for resource in graph.objects(URIRef(catalog_uri), DCAT.resource):
            result.setdefault(str(resource), []).append(catalog_uri)
    return result


def _resource_catalogs(
    store: TripleStore | None,
    uris: Uris,
    resource: str,
    from_files: dict[str, list[str]],
    loaded: set[str],
) -> list[str]:
    """Catálogo en el que queda un esquema o una ontología en ``load-semantic`` (decisión
    50): si ya está en uno del triplestore, ese (un traslado hecho desde la aplicación no se
    deshace); si es nuevo, el de ``data/catalogos/``, que tiene que cargarse en esta
    ejecución o estar ya publicado."""
    current = sorted(bajas.resource_catalogs(store, uris, resource)) if store is not None else []
    if current:
        return current
    targets = sorted(set(from_files.get(resource, [])))
    if not targets:
        raise ingest.IngestError(
            "catalog",
            "El recurso no está en ningún catálogo de data/catalogos/ (dcat:resource) ni del "
            "triplestore",
            [ingest.Issue("Recurso sin catálogo", focus_node=resource)],
        )
    for target in targets:
        if target not in loaded and not (store is not None and bajas.catalog_exists(store, target)):
            raise ingest.IngestError(
                "catalog",
                "El catálogo del recurso no existe, está dado de baja o no está en data/catalogos/",
                [ingest.Issue("Catálogo del recurso", focus_node=target)],
            )
    return targets


def _with_membership(graph: Graph, resource: str, catalogs: list[str]) -> Graph:
    result = Graph()
    for prefix, namespace in graph.namespaces():
        result.bind(prefix, namespace, override=True, replace=True)
    for triple in graph:
        result.add(triple)
    for catalog_uri in catalogs:
        result.add((URIRef(catalog_uri), DCAT.resource, URIRef(resource)))
    return result


def _check_prefix(session: Session, graph: Graph, resource: str) -> None:
    """Decisión 50 (regla 7): el prefijo VANN de un recurso dado de baja no se reutiliza."""
    prefix = vocab_ingest.resource_prefix(graph, resource)
    owner = vocab_ingest.withdrawn_prefix_owner(session, prefix)
    if owner is not None and owner != resource:
        raise ingest.IngestError(
            "prefix_withdrawn",
            f"El prefijo VANN «{prefix}» era de un recurso dado de baja ({owner}) y no se "
            "reutiliza",
        )


def _scheme_paths(semantic_dir: Path) -> list[Path]:
    root = semantic_dir / ingest.VOCABULARIES_DIR
    return sorted(root.glob("*.ttl")) + sorted((root / CORP_SEGMENT).glob("*.ttl"))


def _ontology_paths(semantic_dir: Path) -> list[Path]:
    return sorted((semantic_dir / ingest.ONTOLOGIES_DIR).glob("*/*.ttl"))


def _check_scheme_path(path: Path, prepared: vocab_ingest.PreparedScheme) -> None:
    corp = path.parent.name == CORP_SEGMENT
    if (path.stem, corp) != (prepared.slug, prepared.corp):
        raise ingest.IngestError(
            "uri",
            f"El fichero debe llamarse como el esquema: {prepared.uri} va en "
            f"vocabularios/{'corp/' if prepared.corp else ''}{prepared.slug}.ttl",
        )


def _check_ontology_path(path: Path, prepared: vocab_ingest.PreparedOntology) -> None:
    if (path.parent.name, path.stem) != (prepared.slug, prepared.version):
        raise ingest.IngestError(
            "uri",
            f"El fichero debe ser ontologias/{prepared.slug}/{prepared.version}.ttl "
            f"(owl:versionIRI {prepared.version_iri})",
        )


def _validate_all(
    settings: Settings, uris: Uris, session: Session, store: TripleStore | None = None
) -> tuple[_Plan, bool]:
    """Valida todo y calcula las métricas de las ontologías **antes de escribir**: si un
    fichero falla (también al analizarlo con owlready2, o porque cambiaría una versión ya
    publicada), no se carga ninguno. ``store`` es el triplestore del que se lee lo publicado
    para comprobar la inmutabilidad (``load-semantic`` lo pasa siempre)."""
    semantic_dir = settings.semantic_dir
    plan = _Plan()
    failed = False
    seen: dict[str, str] = {}

    def remember(name: str, graph_uri: str) -> None:
        if graph_uri in seen:
            raise ingest.IngestError(
                "structure", f"El grafo <{graph_uri}> ya lo define {seen[graph_uri]}"
            )
        seen[graph_uri] = name

    # Catálogos (decisión 49). Lo dado de baja desde la aplicación manda sobre los
    # ficheros: un catálogo, una serie, un esquema o una ontología con lápida se omite (su
    # slug no se reutiliza). Van primero porque los esquemas y las ontologías (decisión 50)
    # necesitan saber qué catálogos se cargan.
    plan.withdrawn = bajas.withdrawn_uris(store, uris) if store is not None else set()
    root_file = semantic_dir / ingest.CATALOG_FILE
    try:
        graph = ingest.parse_file(root_file, uris.base, max_triples=settings.ingest_max_triples)
        ingest.validate_plain(graph, semantic_dir, uris.base)
        plan.catalogs.append((str(root_file.relative_to(semantic_dir)), uris.root_catalog, graph))
    except ingest.IngestError as exc:
        _print_ingest_error(str(root_file.relative_to(semantic_dir)), exc)
        failed = True
    loaded_catalogs: set[str] = set()
    for path in _catalog_paths(semantic_dir):
        name = str(path.relative_to(semantic_dir))
        try:
            if not is_slug(path.stem):
                raise ingest.IngestError(
                    "uri", "El nombre del fichero tiene que ser el slug del catálogo"
                )
            catalog_uri = uris.catalog(path.stem)
            if catalog_uri in plan.withdrawn:
                typer.echo(f"  {name}: se omite (catálogo dado de baja)")
                continue
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            ingest.check_catalog_structure(graph, uris, catalog_uri)
            ingest.validate_plain(graph, semantic_dir, uris.base)
            plan.catalogs.append((name, catalog_uri, graph))
            loaded_catalogs.add(catalog_uri)
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True

    # El raíz: no lista series y solo agrupa catálogos catalogo/{slug} que se cargan aquí o
    # ya están publicados (un solo nivel). Los dados de baja se quitan al escribirlo.
    for name, graph_uri, graph in plan.catalogs:
        if graph_uri != uris.root_catalog:
            continue
        root = URIRef(uris.root_catalog)
        problems = [
            ingest.Issue("El catálogo raíz no lista series", value=str(item))
            for item in graph.objects(root, DCAT.dataset)
        ]
        # Decisión 50 (regla 2): dcat:resource sale solo de un catálogo catalogo/{slug}.
        problems += [
            ingest.Issue("El catálogo raíz no lista esquemas ni ontologías", value=str(item))
            for item in graph.objects(root, DCAT.resource)
        ]
        for item in graph.objects(root, DCAT.catalog):
            target = str(item)
            if target in plan.withdrawn:
                continue
            if uris.catalog_slug(target) is None or not (
                target in loaded_catalogs
                or (store is not None and bajas.catalog_exists(store, target))
            ):
                problems.append(
                    ingest.Issue(
                        "dcat:catalog tiene que ser un catálogo catalogo/{slug} existente",
                        value=target,
                    )
                )
        if problems:
            _print_ingest_error(
                name, ingest.IngestError("structure", "Catálogo raíz no válido", problems)
            )
            failed = True

    # Decisión 50: catálogo de cada esquema y ontología según data/catalogos/.
    from_files = _file_memberships(semantic_dir, uris)
    for path in _scheme_paths(semantic_dir):
        name = str(path.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            uri = vocab_ingest.check_scheme_structure(graph, uris).uri
            if uri in plan.withdrawn:
                typer.echo(f"  {name}: se omite (esquema dado de baja)")
                continue
            catalogs = _resource_catalogs(store, uris, uri, from_files, loaded_catalogs)
            source = graph
            if store is not None:
                source = vocab_ingest.merge_published_concepts(store.get_graph(uri), graph, uri)
            prepared = vocab_ingest.prepare_scheme(
                _with_membership(source, uri, catalogs), uris, settings
            )
            _check_scheme_path(path, prepared)
            _check_prefix(session, prepared.graph, prepared.uri)
            remember(name, prepared.uri)
            plan.schemes.append((name, prepared))
            plan.scheme_sources[prepared.uri] = (graph, catalogs)
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True
    # Esquemas auxiliares (vocab/dominio y vocab/tipo-dataset): data/vocab-minimo.ttl se
    # valida entero y se reparte en un grafo por esquema, como el resto de esquemas. No
    # están en ningún catálogo ni se gestionan desde la aplicación.
    auxiliary = semantic_dir / ingest.VOCAB_FILE
    if auxiliary.is_file():  # obligatorio: load_semantic ya lo ha comprobado
        name = str(auxiliary.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(auxiliary, uris.base, max_triples=settings.ingest_max_triples)
            ingest.validate_shacl(graph, semantic_dir, uris.base, support=False)
            for prepared in vocab_ingest.split_schemes(graph, uris):
                remember(name, prepared.uri)
                plan.schemes.append((f"{name} ({prepared.slug})", prepared))
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True
    # Sustitutos (dct:isReplacedBy) vivos: de los esquemas de esta ejecución o publicados.
    known = _known_concepts(plan)
    for name, prepared in plan.schemes:
        try:
            vocab_ingest.check_replacements(store or MemoryStore(), uris, prepared, known)
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True
    for path in _ontology_paths(semantic_dir):
        name = str(path.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            uri = vocab_ingest.check_ontology_structure(graph, uris).uri
            if uri in plan.withdrawn:
                typer.echo(f"  {name}: se omite (ontología dada de baja)")
                continue
            catalogs = _resource_catalogs(store, uris, uri, from_files, loaded_catalogs)
            prepared_onto = vocab_ingest.prepare_ontology(
                _with_membership(graph, uri, catalogs), uris, settings
            )
            _check_ontology_path(path, prepared_onto)
            _check_prefix(session, prepared_onto.graph, prepared_onto.uri)
            remember(name, prepared_onto.version_iri)
            if store is not None:
                vocab_ingest.check_ontology_immutable(store, prepared_onto)
            analysis = vocab_ingest.analyze_ontology(prepared_onto, settings, session)
            plan.ontologies.append((name, prepared_onto, analysis))
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True

    plain_files: list[tuple[Path, str]] = []
    externas = semantic_dir / ingest.EXTERNAL_ONTOLOGIES_FILE
    if externas.is_file():
        plain_files.append((externas, uris.external_ontologies_graph))
    for path, graph_uri in plain_files:
        name = str(path.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            vocab_ingest.prepare_external(graph, uris, settings)
            plan.plain.append((name, graph_uri, graph))
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True

    series_dir = semantic_dir / ingest.SYNTHETIC_DIR
    for path in sorted(series_dir.glob("*.ttl")):
        name = str(path.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            prepared_series = ingest.prepare_series(graph, uris, semantic_dir)
            if prepared_series.uri in plan.withdrawn:
                typer.echo(f"  {name}: se omite (dataset dado de baja)")
                continue
            if store is not None:
                ingest.check_immutable(store.get_graph(prepared_series.uri), prepared_series)
                _check_series_catalog(store, uris, prepared_series, loaded_catalogs)
            plan.series.append((name, prepared_series))
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True
    if _check_files(semantic_dir, settings, uris, session, plan):
        failed = True
    return plan, failed


@cli.command("load-semantic")
def load_semantic() -> None:
    """Carga esquemas SKOS, ontologías (todas las versiones), externas, catálogo y series.

    Lee ``SEMANTIC_DIR``: ``vocabularios/*.ttl`` y ``vocabularios/corp/*.ttl``,
    ``data/vocab-minimo.ttl`` (esquemas auxiliares, uno por grafo),
    ``ontologias/{slug}/{version}.ttl``, ``ontologias/externas.ttl``, ``data/catalogo.ttl``
    (catálogo raíz), ``data/catalogos/{slug}.ttl`` (un catálogo por fichero),
    ``data/sintetico/*.ttl`` y los ficheros de distribución de
    ``data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}`` (con las reglas de la API).
    Las versiones ya publicadas son inmutables (decisión 28) y las nuevas se encolan para
    evaluarlas con F-UJI (las evalúa el trabajador de la API).
    Decisión 49: lo hecho desde la aplicación se conserva. Los catálogos y las series dados
    de baja se omiten (con sus ficheros), una serie que ya está en un catálogo se queda en
    él, y los catálogos creados por la API siguen en el raíz.
    Decisión 50: igual con los esquemas y las ontologías propias (se omiten los dados de
    baja, uno que ya está en un catálogo se queda en él y uno nuevo va al catálogo que le
    da ``data/catalogos/``), y no se quitan los conceptos añadidos desde la aplicación.
    Valida todo antes de escribir nada: si un fichero no es válido, no se carga ninguno. Es
    idempotente: un grafo con el mismo contenido no se reescribe, y las métricas de una
    versión de ontología solo se recalculan si su contenido ha cambiado.
    """
    settings = get_settings()
    uris = Uris(settings.base_uri)
    semantic_dir = settings.semantic_dir
    required = [semantic_dir / ingest.VOCAB_FILE, semantic_dir / ingest.CATALOG_FILE]
    series_dir = semantic_dir / ingest.SYNTHETIC_DIR
    series_paths = sorted(series_dir.glob("*.ttl")) if series_dir.is_dir() else []
    missing = [path for path in required if not path.is_file()]
    if missing or not series_paths:
        for path in missing:
            typer.echo(f"No existe {path}", err=True)
        if not series_paths:
            typer.echo(f"No hay ficheros .ttl en {series_dir}", err=True)
        raise typer.Exit(code=2)

    session = get_sessionmaker()()
    try:
        # 1. Validar todo (y calcular métricas). Del triplestore solo se lee, para comprobar
        # que no cambia ninguna versión ya publicada (decisión 28).
        store = get_store(settings)
        plan, failed = _validate_all(settings, uris, session, store)
        if failed:
            typer.echo("Validación fallida: no se ha cargado nada.", err=True)
            raise typer.Exit(code=1)

        # 2. Escribir, con el bloqueo de las escrituras del catálogo (QA-49-01 y QA-49-03).
        # La validación (con el razonador) va fuera; lo dado de baja mientras se validaba se
        # omite. Desde la decisión 50 los esquemas y las ontologías también van dentro:
        # comparten con el CRUD los grafos de los catálogos (dcat:resource) y las bajas.
        # Primero los catálogos, para que existan antes de enlazar sus recursos.
        with write_lock.catalog_write_lock(session):
            _skip_withdrawn_meanwhile(store, uris, plan)
            _write_catalogs(store, uris, plan)
            _write_schemes_and_ontologies(store, session, settings, uris, plan)
            _write_series_and_files(store, session, settings, uris, plan)
    except TriplestoreError as exc:
        typer.echo(f"Error del triplestore: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except StorageError as exc:
        typer.echo(f"Error del almacenamiento: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except write_lock.CatalogLockTimeoutError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        session.close()


if __name__ == "__main__":
    cli()
