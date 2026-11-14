"""CLI de administración del backend.

Uso::

    uv run python -m app.cli create-admin --username <nombre>
    printf '%s' "$PASSWORD" | uv run python -m app.cli create-admin --username <nombre> \
        --password-stdin

La contraseña nunca se pasa como argumento (quedaría en el historial y en ``ps``):
se pide de forma interactiva, oculta y con confirmación, o se lee de stdin.
"""

import re
import sys
from typing import Annotated

import typer

from app.db import get_sessionmaker
from app.models import Role
from app.schemas import USERNAME_PATTERN
from app.security import PASSWORD_MIN_LENGTH
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


if __name__ == "__main__":
    cli()
