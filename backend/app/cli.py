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
from typing import Annotated

import typer
from rdflib import Graph

from app import ingest
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.models import Role
from app.schemas import USERNAME_PATTERN
from app.security import PASSWORD_MIN_LENGTH
from app.triplestore import FusekiStore, TripleStore, TriplestoreError
from app.uris import Uris
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


@cli.command("load-semantic")
def load_semantic() -> None:
    """Carga el vocabulario mínimo, el catálogo y las series de ``data/sintetico/``.

    Lee ``SEMANTIC_DIR``. Valida todo antes de escribir nada: si un fichero no es válido,
    no se carga ninguno. Es idempotente: un grafo con el mismo contenido no se reescribe.
    """
    settings = get_settings()
    uris = Uris(settings.base_uri)
    semantic_dir = settings.semantic_dir
    vocab_path = semantic_dir / ingest.VOCAB_FILE
    catalog_path = semantic_dir / ingest.CATALOG_FILE
    series_dir = semantic_dir / ingest.SYNTHETIC_DIR
    series_paths = sorted(series_dir.glob("*.ttl")) if series_dir.is_dir() else []

    missing = [p for p in (vocab_path, catalog_path) if not p.is_file()]
    if missing or not series_paths:
        for path in missing:
            typer.echo(f"No existe {path}", err=True)
        if not series_paths:
            typer.echo(f"No hay ficheros .ttl en {series_dir}", err=True)
        raise typer.Exit(code=2)

    # 1. Validar todo.
    failed = False
    plain: list[tuple[str, str, Graph]] = []
    prepared: list[tuple[str, ingest.PreparedSeries]] = []
    for path, graph_uri in ((vocab_path, uris.vocab_graph), (catalog_path, uris.catalog)):
        try:
            graph = ingest.parse_file(path, uris.base)
            ingest.validate_plain(graph, semantic_dir, uris.base)
            plain.append((path.name, graph_uri, graph))
        except ingest.IngestError as exc:
            _print_ingest_error(path.name, exc)
            failed = True
    for path in series_paths:
        try:
            graph = ingest.parse_file(path, uris.base)
            prepared.append((path.name, ingest.prepare_series(graph, uris, semantic_dir)))
        except ingest.IngestError as exc:
            _print_ingest_error(path.name, exc)
            failed = True
    if failed:
        typer.echo("Validación fallida: no se ha cargado nada.", err=True)
        raise typer.Exit(code=1)

    # 2. Escribir.
    store = get_store(settings)
    session = get_sessionmaker()()
    try:
        for name, graph_uri, graph in plain:
            _created, changed = ingest.store_graph(store, graph_uri, graph)
            typer.echo(f"{name} -> <{graph_uri}>: {'cargado' if changed else 'sin cambios'}")
        for name, series in prepared:
            result = ingest.publish_and_audit(
                store, session, series, actor_username=CLI_ACTOR, via="cli"
            )
            state = "cargado" if result.changed else "sin cambios"
            typer.echo(
                f"{name} -> <{result.graph_uri}>: {state} "
                f"(versiones {', '.join(result.versions) or '-'})"
            )
    except TriplestoreError as exc:
        typer.echo(f"Error del triplestore: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        session.close()


if __name__ == "__main__":
    cli()
