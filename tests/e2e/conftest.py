"""Entorno de las pruebas de extremo a extremo de las puertas (G1 y G2).

Levanta el ``docker-compose.yml`` real del repositorio en un proyecto de Compose propio
(``itot-e2e-<aleatorio>``), con puertos libres elegidos al vuelo y un fichero de entorno
temporal generado a partir de ``.env.example``. Al terminar lo apaga y borra sus
volúmenes e imágenes. No toca el ``.env`` ni el entorno de desarrollo de la máquina.

Solo usa la biblioteca estándar y pytest. Ver ``tests/e2e/README.md``.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

UP_TIMEOUT_SECONDS = int(os.environ.get("E2E_UP_TIMEOUT", "900"))
HTTP_TIMEOUT_SECONDS = 15


# --- Utilidades ----------------------------------------------------------------------


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    text: str

    def json(self) -> object:
        return json.loads(self.text)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """No sigue redirecciones: urllib las entrega entonces como ``HTTPError`` 3xx."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def http(
    method: str,
    url: str,
    *,
    form: dict[str, str] | None = None,
    json_body: object | None = None,
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
    token: str | None = None,
    follow_redirects: bool = True,
) -> Response:
    """Petición HTTP con urllib. Devuelve también las respuestas 4xx y 5xx.

    Con ``follow_redirects=False`` devuelve la propia respuesta 3xx (con su ``Location``)
    en lugar de seguirla.
    """
    request_headers = dict(headers or {})
    data = raw_body
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        request_headers.setdefault("Content-Type", "application/json")
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    if not url.startswith("http://127.0.0.1:"):
        # Las pruebas de seguridad solo se lanzan contra el entorno local del proyecto.
        raise ValueError(f"URL fuera del entorno local de pruebas: {url}")
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)  # noqa: S310
    opener = urllib.request.urlopen if follow_redirects else _NO_REDIRECT_OPENER.open
    try:
        with opener(request, timeout=HTTP_TIMEOUT_SECONDS) as raw:
            return Response(
                raw.status,
                {k.lower(): v for k, v in raw.headers.items()},
                raw.read().decode("utf-8", "replace"),
            )
    except urllib.error.HTTPError as error:
        return Response(
            error.code,
            {k.lower(): v for k, v in error.headers.items()},
            error.read().decode("utf-8", "replace"),
        )


def wait_for_http(url: str, *, timeout: float = 90.0) -> Response:
    """Reintenta un GET hasta que el servicio acepta conexiones.

    Hace falta para los servicios sin healthcheck en el Compose (el frontend): para
    ellos ``docker compose up --wait`` solo garantiza que el contenedor ha arrancado.
    """
    import time
    from http.client import HTTPException

    deadline = time.monotonic() + timeout
    while True:
        try:
            return http("GET", url)
        except OSError, HTTPException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


def _free_ports(count: int) -> list[int]:
    """Puertos TCP libres en 127.0.0.1 (se reservan todos antes de soltarlos)."""
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def _read_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


@dataclass
class Stack:
    """El entorno levantado: comandos de Compose, URLs y secretos generados."""

    project: str
    workdir: Path
    env_file: Path
    override_file: Path
    env: dict[str, str]
    example_env: dict[str, str]
    ports: dict[str, int]
    # Todo lo que nunca debe aparecer en la auditoría ni en los logs.
    sensitive: dict[str, str] = field(default_factory=dict)

    @property
    def api(self) -> str:
        return f"http://127.0.0.1:{self.ports['backend']}"

    @property
    def frontend(self) -> str:
        return f"http://127.0.0.1:{self.ports['frontend']}"

    @property
    def fuseki(self) -> str:
        return f"http://127.0.0.1:{self.ports['fuseki']}"

    @property
    def frontend_origin(self) -> str:
        return f"http://localhost:{self.ports['frontend']}"

    def _base(self, *, with_override: bool = True) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(REPO_ROOT),
            "--env-file",
            str(self.env_file),
            "--file",
            str(COMPOSE_FILE),
        ]
        if with_override:
            command += ["--file", str(self.override_file)]
        return command

    def compose(
        self,
        *args: str,
        stdin: str | None = None,
        timeout: int = 120,
        with_override: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [*self._base(with_override=with_override), *args]
        if stdin is None:
            return subprocess.run(  # noqa: S603 - comando fijo, sin shell
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        return subprocess.run(  # noqa: S603 - comando fijo, sin shell
            command, input=stdin, capture_output=True, text=True, timeout=timeout, check=False
        )

    def psql(self, sql: str) -> list[str]:
        """Ejecuta SQL de solo lectura dentro del contenedor de PostgreSQL."""
        result = self.compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            self.env["POSTGRES_USER"],
            "-d",
            self.env["POSTGRES_DB"],
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-c",
            sql,
        )
        assert result.returncode == 0, result.stderr
        return [line for line in result.stdout.splitlines() if line]

    def remember(self, name: str, value: str) -> str:
        self.sensitive[name] = value
        return value


def _docker_available() -> str | None:
    """Devuelve el motivo por el que no se puede ejecutar, o ``None`` si se puede."""
    if shutil.which("docker") is None:
        return "docker no está instalado"
    info = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if info.returncode != 0:
        return "el demonio de Docker no responde"
    version = subprocess.run(
        ["docker", "compose", "version", "--short"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if version.returncode != 0:
        return "falta Docker Compose v2"
    return None


def _build_stack(workdir: Path) -> Stack:
    example = _read_env_example()
    pg_port, fuseki_port, backend_port, frontend_port = _free_ports(4)

    env = dict(example)
    # Secretos generados al vuelo: nunca los valores ficticios de .env.example.
    postgres_password = secrets.token_hex(16)
    env["POSTGRES_PASSWORD"] = postgres_password
    env["DATABASE_URL"] = (
        f"postgresql+psycopg://{env['POSTGRES_USER']}:{postgres_password}"
        f"@postgres:5432/{env['POSTGRES_DB']}"
    )
    # Sin / & \ : la imagen de Fuseki aplica esta contraseña con sed.
    env["FUSEKI_ADMIN_PASSWORD"] = secrets.token_hex(16)
    env["JWT_SECRET"] = secrets.token_hex(32)
    env["CORS_ORIGINS"] = f"http://localhost:{frontend_port}"
    env["VITE_API_BASE_URL"] = f"http://localhost:{backend_port}"
    # Fase 2: el backend redirige (303) las URIs persistentes a la ficha del frontend.
    env["FRONTEND_BASE_URL"] = f"http://localhost:{frontend_port}"
    # Variables opcionales del Compose para no chocar con otros servicios de la máquina.
    env["POSTGRES_HOST_PORT"] = str(pg_port)
    env["FUSEKI_HOST_PORT"] = str(fuseki_port)
    env["BACKEND_HOST_PORT"] = str(backend_port)
    env["FRONTEND_HOST_PORT"] = str(frontend_port)

    env_file = workdir / "e2e.env"
    env_file.touch(mode=0o600)
    env_file.write_text("".join(f"{key}={value}\n" for key, value in env.items()), "utf-8")

    # En docker-compose.yml el backend carga `env_file: .env` de la raíz. Para no leer ni
    # pisar el .env del desarrollador, este fichero adicional apunta ese env_file al
    # temporal. Es lo único que cambia: puertos, imágenes, healthchecks, dependencias y el
    # entorno del resto de servicios (el frontend solo recibe sus VITE_*) son los reales.
    override_file = workdir / "docker-compose.e2e.yml"
    override_file.write_text(
        f"services:\n  backend:\n    env_file: !override\n      - {env_file}\n",
        "utf-8",
    )

    stack = Stack(
        project=f"itot-e2e-{secrets.token_hex(4)}",
        workdir=workdir,
        env_file=env_file,
        override_file=override_file,
        env=env,
        example_env=example,
        ports={
            "postgres": pg_port,
            "fuseki": fuseki_port,
            "backend": backend_port,
            "frontend": frontend_port,
        },
    )
    stack.remember("POSTGRES_PASSWORD", postgres_password)
    stack.remember("FUSEKI_ADMIN_PASSWORD", env["FUSEKI_ADMIN_PASSWORD"])
    stack.remember("JWT_SECRET", env["JWT_SECRET"])
    return stack


# --- Fixtures ------------------------------------------------------------------------


@pytest.fixture(scope="session")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    reason = _docker_available()
    if reason is not None:
        if os.environ.get("E2E_REQUIRE_DOCKER") == "1":
            pytest.fail(f"Las pruebas de extremo a extremo necesitan Docker: {reason}")
        pytest.skip(f"Las pruebas de extremo a extremo necesitan Docker: {reason}")

    stack = _build_stack(tmp_path_factory.mktemp("g1"))
    keep = os.environ.get("E2E_KEEP") == "1"
    try:
        up = stack.compose(
            "up",
            "--detach",
            "--build",
            "--wait",
            "--wait-timeout",
            str(UP_TIMEOUT_SECONDS),
            timeout=UP_TIMEOUT_SECONDS + 120,
        )
        if up.returncode != 0:
            ps = stack.compose("ps", "--all").stdout
            logs = stack.compose("logs", "--no-color", "--tail", "60").stdout
            pytest.fail(
                "docker compose up no ha dejado el entorno listo.\n"
                f"--- salida ---\n{up.stderr[-4000:]}\n--- ps ---\n{ps}\n"
                f"--- logs ---\n{logs[-8000:]}"
            )
        yield stack
    finally:
        if keep:
            print(f"\nE2E_KEEP=1: el proyecto {stack.project} sigue levantado.")
        else:
            stack.compose("down", "--volumes", "--remove-orphans", "--rmi", "local", timeout=300)
            stack.env_file.unlink(missing_ok=True)


@dataclass(frozen=True)
class Account:
    username: str
    password: str
    role: str
    id: str | None = None
    token: str | None = None


def login(stack: Stack, username: str, password: str) -> Response:
    return http(
        "POST", f"{stack.api}/auth/token", form={"username": username, "password": password}
    )


@pytest.fixture(scope="session")
def admin(stack: Stack) -> Account:
    """Crea el primer admin con la CLI del backend, leyendo la contraseña de stdin."""
    username = f"e2e-admin-{secrets.token_hex(3)}"
    password = stack.remember("contraseña del admin", secrets.token_urlsafe(24))
    result = stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "app.cli",
        "create-admin",
        "--username",
        username,
        "--password-stdin",
        stdin=password + "\n",
    )
    assert result.returncode == 0, f"create-admin falló:\n{result.stdout}\n{result.stderr}"
    assert username in result.stdout
    assert password not in result.stdout + result.stderr

    response = login(stack, username, password)
    assert response.status == 200, response.text
    token = stack.remember("token del admin", response.json()["access_token"])  # type: ignore[index]
    me = http("GET", f"{stack.api}/auth/me", token=token)
    assert me.status == 200, me.text
    return Account(username, password, "admin", id=me.json()["id"], token=token)  # type: ignore[index]


def create_account(stack: Stack, admin: Account, role: str) -> Account:
    """Da de alta una cuenta nueva con el admin y devuelve sus credenciales y su token."""
    return _create_account(stack, admin, role)


def _create_account(stack: Stack, admin: Account, role: str) -> Account:
    username = f"e2e-{role}-{secrets.token_hex(3)}"
    password = stack.remember(f"contraseña de {role}", secrets.token_urlsafe(24))
    created = http(
        "POST",
        f"{stack.api}/users",
        json_body={"username": username, "password": password, "role": role},
        token=admin.token,
    )
    assert created.status == 201, created.text
    response = login(stack, username, password)
    assert response.status == 200, response.text
    token = stack.remember(f"token de {role}", response.json()["access_token"])  # type: ignore[index]
    return Account(username, password, role, id=created.json()["id"], token=token)  # type: ignore[index]


@pytest.fixture(scope="session")
def member(stack: Stack, admin: Account) -> Account:
    return _create_account(stack, admin, "miembro")


@pytest.fixture(scope="session")
def editor(stack: Stack, admin: Account) -> Account:
    return _create_account(stack, admin, "editor")
