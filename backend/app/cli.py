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
from sqlalchemy.orm import Session

from app import distributions, ingest, vocab_ingest
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.models import DistributionFile, Role
from app.schemas import USERNAME_PATTERN
from app.security import PASSWORD_MIN_LENGTH
from app.storage import Storage, StorageError, hash_stream, storage_from_settings
from app.triplestore import FusekiStore, TripleStore, TriplestoreError
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
    ontologies: list[tuple[str, vocab_ingest.PreparedOntology, vocab_ingest.OntologyAnalysis]] = (
        field(default_factory=list)
    )
    plain: list[tuple[str, str, Graph]] = field(default_factory=list)
    series: list[tuple[str, ingest.PreparedSeries]] = field(default_factory=list)
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
    seen: set[str] = set()
    limit = settings.max_upload_mb * 1024 * 1024
    for path in _file_paths(semantic_dir):
        name = str(path.relative_to(semantic_dir))
        slug, version, dist = path.parent.parent.name, path.parent.name, path.stem
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

    for path in _scheme_paths(semantic_dir):
        name = str(path.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            prepared = vocab_ingest.prepare_scheme(graph, uris, settings)
            _check_scheme_path(path, prepared)
            remember(name, prepared.uri)
            plan.schemes.append((name, prepared))
        except ingest.IngestError as exc:
            _print_ingest_error(name, exc)
            failed = True
    # Esquemas auxiliares (vocab/dominio y vocab/tipo-dataset): data/vocab-minimo.ttl se
    # valida entero y se reparte en un grafo por esquema, como el resto de esquemas.
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
    for path in _ontology_paths(semantic_dir):
        name = str(path.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            prepared_onto = vocab_ingest.prepare_ontology(graph, uris, settings)
            _check_ontology_path(path, prepared_onto)
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
    plain_files.append((semantic_dir / ingest.CATALOG_FILE, uris.catalog))
    for path, graph_uri in plain_files:
        name = str(path.relative_to(semantic_dir))
        try:
            graph = ingest.parse_file(path, uris.base, max_triples=settings.ingest_max_triples)
            if path == externas:
                vocab_ingest.prepare_external(graph, uris, settings)
            else:
                ingest.validate_plain(graph, semantic_dir, uris.base)
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
            if store is not None:
                ingest.check_immutable(store.get_graph(prepared_series.uri), prepared_series)
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
    ``ontologias/{slug}/{version}.ttl``, ``ontologias/externas.ttl``, ``data/catalogo.ttl``,
    ``data/sintetico/*.ttl`` y los ficheros de distribución de
    ``data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}`` (con las reglas de la API).
    Las versiones ya publicadas son inmutables (decisión 28) y las nuevas se encolan para
    evaluarlas con F-UJI (las evalúa el trabajador de la API).
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

        # 2. Escribir.
        for name, scheme in plan.schemes:
            result = vocab_ingest.publish_scheme_and_audit(
                store, session, scheme, actor_username=CLI_ACTOR, via="cli"
            )
            state = "cargado" if result.changed else "sin cambios"
            typer.echo(f"{name} -> <{result.graph_uri}>: {state} ({result.concepts} conceptos)")
        for name, graph_uri, graph in plan.plain:
            if graph_uri == uris.catalog:
                # Decisión 29: se conservan los dcat:dataset de las series publicadas.
                graph = ingest.merge_catalog(store.get_graph(graph_uri), graph, uris)
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
            )
            state = "cargado" if onto.changed else "sin cambios"
            metrics = "métricas calculadas" if onto.metrics_recomputed else "métricas al día"
            typer.echo(f"{name} -> <{onto.graph_uri}>: {state}, {metrics}")
        for name, series in plan.series:
            published = ingest.publish_and_audit(
                store, session, series, actor_username=CLI_ACTOR, via="cli"
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
    except TriplestoreError as exc:
        typer.echo(f"Error del triplestore: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except StorageError as exc:
        typer.echo(f"Error del almacenamiento: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        session.close()


if __name__ == "__main__":
    cli()
