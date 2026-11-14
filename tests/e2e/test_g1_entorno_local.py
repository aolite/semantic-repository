"""Puerta G1 · «entorno local listo», de extremo a extremo sobre Docker Compose.

Recorre el criterio de la puerta: los cuatro servicios de la fase 1 arrancan y están
sanos, el primer admin se crea por CLI, el login devuelve un JWT, ``/auth/me`` responde,
los roles se aplican y todo queda en la auditoría de PostgreSQL sin contraseñas ni tokens.

Las pruebas comparten un único entorno (fixture ``stack``) y se ejecutan en el orden del
fichero. Cómo lanzarlas: ``tests/e2e/README.md``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid

import pytest
from conftest import Account, Stack, http, login

PHASE_1_SERVICES = {"postgres", "fuseki", "backend", "frontend"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64_json(segment: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def _sign_hs256(claims: dict, secret: str) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    signing_input = f"{header}.{_b64(json.dumps(claims).encode())}"
    digest = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(digest)}"


def _ps(stack: Stack) -> dict[str, dict]:
    result = stack.compose("ps", "--all", "--format", "json")
    assert result.returncode == 0, result.stderr
    text = result.stdout.strip()
    # Según la versión de Compose, una lista JSON o un objeto por línea.
    rows = json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines()]
    return {row["Service"]: row for row in rows}


# --- 1. El entorno arranca y está sano -----------------------------------------------


def test_los_cuatro_servicios_de_la_fase_1_estan_en_marcha(stack: Stack) -> None:
    services = _ps(stack)
    assert set(services) == PHASE_1_SERVICES
    for name, row in services.items():
        assert row["State"] == "running", f"{name}: {row['State']}"
    for name in ("postgres", "fuseki", "backend"):
        assert services[name]["Health"] == "healthy", f"{name}: {services[name]['Health']}"
    # El frontend no declara healthcheck en la fase 1: si lo declara, debe estar sano;
    # en cualquier caso, se comprueba por HTTP en test_el_frontend_responde.
    assert services["frontend"]["Health"] in ("", "healthy")


def test_el_backend_esta_vivo_y_listo(stack: Stack) -> None:
    live = http("GET", f"{stack.api}/health")
    assert (live.status, live.json()) == (200, {"status": "ok"})

    ready = http("GET", f"{stack.api}/health/ready")
    assert ready.status == 200, ready.text
    body = ready.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["fuseki"]["status"] == "ok"


def test_fuseki_responde_a_una_consulta_ask(stack: Stack) -> None:
    dataset = stack.env["FUSEKI_DATASET"]
    response = http(
        "GET",
        f"{stack.fuseki}/{dataset}/sparql?query=ASK%20%7B%7D",
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    assert response.json()["boolean"] is True


def test_el_frontend_responde(stack: Stack) -> None:
    response = http("GET", f"{stack.frontend}/")
    assert response.status == 200
    assert '<div id="root">' in response.text


def test_las_migraciones_han_creado_las_tablas(stack: Stack) -> None:
    tables = stack.psql(
        "select table_name from information_schema.tables where table_schema = 'public'"
    )
    assert {"users", "audit_events", "alembic_version"} <= set(tables)


def test_los_servicios_solo_se_publican_en_localhost(stack: Stack) -> None:
    """La prueba no cambia los puertos del Compose: solo da valor a las variables
    ``*_HOST_PORT``. Lo que se comprueba es lo que declara docker-compose.yml."""
    result = stack.compose("config", "--format", "json")
    assert result.returncode == 0, f"docker compose config falló:\n{result.stderr}"
    services = json.loads(result.stdout)["services"]
    for name in sorted(PHASE_1_SERVICES):
        ports = services[name]["ports"]
        assert ports, name
        for port in ports:
            assert port.get("host_ip") == "127.0.0.1", f"{name}: {port}"
            assert str(port["published"]) == str(stack.ports[name]), f"{name}: {port}"


def test_la_administracion_de_fuseki_exige_credenciales(stack: Stack) -> None:
    for path in ("/$/datasets", "/$/server", "/$/backup/" + stack.env["FUSEKI_DATASET"]):
        assert http("GET", f"{stack.fuseki}{path}").status == 401, path
        assert http("POST", f"{stack.fuseki}{path}").status == 401, path


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Hallazgo de qa (gravedad alta, dueño: infra): Fuseki acepta escrituras anónimas "
        "(SPARQL Update y Graph Store) en el dataset, desde el host y desde cualquier "
        "contenedor de la red. Incumple la regla «solo el backend escribe en el "
        "triplestore» (Plan.md, sección 1)."
    ),
)
def test_fuseki_rechaza_escrituras_anonimas(stack: Stack) -> None:
    dataset = stack.env["FUSEKI_DATASET"]
    marker = f"urn:qa-e2e:{secrets.token_hex(6)}"
    update = http(
        "POST",
        f"{stack.fuseki}/{dataset}/update",
        form={"update": f'INSERT DATA {{ GRAPH <{marker}> {{ <{marker}> <{marker}> "qa" }} }}'},
    )
    graph_store = http(
        "POST",
        f"{stack.fuseki}/{dataset}/data?graph={marker}:gsp",
        raw_body=f'<{marker}> <{marker}> "gsp" .'.encode(),
        headers={"Content-Type": "text/turtle"},
    )
    # Limpieza por si la escritura ha entrado (el entorno se destruye al terminar igualmente).
    for graph in (marker, f"{marker}:gsp"):
        http(
            "POST",
            f"{stack.fuseki}/{dataset}/update",
            form={"update": f"DROP SILENT GRAPH <{graph}>"},
        )
    assert update.status in (401, 403), f"SPARQL Update anónimo: {update.status}"
    assert graph_store.status in (401, 403), f"Graph Store anónimo: {graph_store.status}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Hallazgo de qa (gravedad media, dueño: infra): el servicio frontend recibe todo el "
        ".env (`env_file: .env`), incluidos JWT_SECRET, DATABASE_URL y las contraseñas de "
        "PostgreSQL y Fuseki, que solo necesita el backend."
    ),
)
def test_el_frontend_no_recibe_los_secretos_del_backend(stack: Stack) -> None:
    result = stack.compose("exec", "-T", "frontend", "env")
    assert result.returncode == 0, result.stderr
    names = {line.partition("=")[0] for line in result.stdout.splitlines()}
    backend_only = {"JWT_SECRET", "DATABASE_URL", "POSTGRES_PASSWORD", "FUSEKI_ADMIN_PASSWORD"}
    assert names & backend_only == set()


def test_vite_no_sirve_al_navegador_variables_sin_prefijo(stack: Stack) -> None:
    """Aunque el contenedor tenga los secretos, Vite solo expone las variables ``VITE_``."""
    for path in ("/src/config.ts", "/src/main.tsx", "/@vite/client", "/.env", "/@fs/app/.env"):
        response = http("GET", f"{stack.frontend}{path}")
        for name, secret in stack.sensitive.items():
            assert secret not in response.text, f"{path} expone {name}"


def test_el_backend_no_se_ejecuta_como_root(stack: Stack) -> None:
    result = stack.compose("exec", "-T", "backend", "id", "-u")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != "0"


def test_el_frontend_no_se_ejecuta_como_root(stack: Stack) -> None:
    result = stack.compose("exec", "-T", "frontend", "id", "-u")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != "0"


def test_no_hay_usuarios_por_defecto(stack: Stack) -> None:
    """Antes de crear el admin no existe ninguna cuenta (ningún usuario se versiona)."""
    if stack.sensitive.get("token del admin"):
        return  # se ha ejecutado suelta, después de crear el admin: no aplica
    assert stack.psql("select count(*) from users") == ["0"]
    guesses = ["admin", "administrator", "root", "itot", "password", "change-me", "admin1234567"]
    for username in ("admin", "root", "itot"):
        for password in guesses:
            assert login(stack, username, password).status == 401
    assert http("GET", f"{stack.api}/users").status == 401


# --- 2. Primer admin por CLI ---------------------------------------------------------


def test_create_admin_por_cli(stack: Stack, admin: Account) -> None:
    rows = stack.psql("select username, role, is_active from users")
    assert f"{admin.username}|admin|t" in rows
    hashes = stack.psql("select password_hash from users")
    assert hashes
    assert all(value.startswith("$argon2id$") for value in hashes)
    assert all(admin.password not in value for value in hashes)


def test_create_admin_rechaza_duplicados_y_contrasenas_cortas(stack: Stack, admin: Account) -> None:
    base = ["exec", "-T", "backend", "python", "-m", "app.cli", "create-admin"]

    other_password = secrets.token_urlsafe(24)
    duplicate = stack.compose(
        *base, "--username", admin.username, "--password-stdin", stdin=other_password + "\n"
    )
    assert duplicate.returncode == 1
    assert other_password not in duplicate.stdout + duplicate.stderr

    short = stack.compose(
        *base, "--username", "e2e-corta", "--password-stdin", stdin=secrets.token_hex(3) + "\n"
    )
    assert short.returncode == 2

    # La contraseña no se admite como argumento (quedaría en `ps` y en el historial).
    as_argument = stack.compose(*base, "--username", "e2e-arg", "--password", other_password)
    assert as_argument.returncode != 0

    assert stack.psql("select count(*) from users where role = 'admin'") == ["1"]
    # La contraseña original sigue valiendo: el duplicado no la ha cambiado.
    assert login(stack, admin.username, admin.password).status == 200
    assert login(stack, admin.username, other_password).status == 401


# --- 3. Login y /auth/me -------------------------------------------------------------


def test_login_devuelve_un_jwt_con_el_rol(stack: Stack, admin: Account) -> None:
    response = login(stack, admin.username, admin.password)
    assert response.status == 200, response.text
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "role"}
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"
    assert body["expires_in"] == int(stack.env["JWT_EXPIRE_MINUTES"]) * 60
    stack.remember("otro token del admin", body["access_token"])

    header, payload, _signature = body["access_token"].split(".")
    assert _b64_json(header)["alg"] == stack.env["JWT_ALGORITHM"]
    claims = _b64_json(payload)
    assert claims["sub"] == admin.id
    assert claims["role"] == "admin"
    assert claims["exp"] - claims["iat"] == body["expires_in"]
    assert "password" not in json.dumps(claims).lower()


def test_login_fallido_no_distingue_usuario_de_contrasena(stack: Stack, admin: Account) -> None:
    wrong_password = stack.remember("contraseña equivocada", secrets.token_urlsafe(24))
    bad_password = login(stack, admin.username, wrong_password)
    unknown_user = login(stack, f"e2e-fantasma-{secrets.token_hex(3)}", wrong_password)
    assert bad_password.status == unknown_user.status == 401
    assert bad_password.text == unknown_user.text
    assert bad_password.headers.get("www-authenticate") == "Bearer"
    assert "access_token" not in bad_password.text


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Hallazgo de qa (gravedad media, dueño: backend): un byte nulo en `username` hace "
        "que POST /auth/token devuelva 500 con PostgreSQL (psycopg.DataError), sin "
        "autenticación y sin dejar rastro en la auditoría. Con SQLite no se reproduce."
    ),
)
def test_login_con_byte_nulo_no_provoca_un_500(stack: Stack, admin: Account) -> None:
    """PostgreSQL no admite el byte nulo en un texto: debe ser un 4xx, no un error interno."""
    response = http(
        "POST",
        f"{stack.api}/auth/token",
        raw_body=b"username=admin%00x&password=" + secrets.token_hex(8).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status in (400, 401, 422), f"{response.status}: {response.text[:300]}"
    assert http("GET", f"{stack.api}/health/ready").status == 200


def test_auth_me(stack: Stack, admin: Account) -> None:
    response = http("GET", f"{stack.api}/auth/me", token=admin.token)
    assert response.status == 200, response.text
    body = response.json()
    assert set(body) == {"id", "username", "role", "is_active", "created_at", "updated_at"}
    assert (body["username"], body["role"], body["is_active"]) == (admin.username, "admin", True)

    anonymous = http("GET", f"{stack.api}/auth/me")
    assert anonymous.status == 401
    assert anonymous.headers.get("www-authenticate") == "Bearer"


def test_tokens_manipulados_o_firmados_con_otro_secreto(stack: Stack, admin: Account) -> None:
    assert admin.token is not None
    header, payload, signature = admin.token.split(".")
    claims = _b64_json(payload)

    # Firma alterada.
    flipped = signature[:-2] + ("AA" if not signature.endswith("AA") else "BB")
    assert http("GET", f"{stack.api}/auth/me", token=f"{header}.{payload}.{flipped}").status == 401

    # Mismo contenido, firmado con el secreto ficticio de .env.example: el entorno de
    # la prueba no lo usa, así que debe rechazarse.
    placeholder_secret = stack.example_env["JWT_SECRET"]
    assert placeholder_secret != stack.env["JWT_SECRET"]
    forged = _sign_hs256(claims, placeholder_secret)
    assert http("GET", f"{stack.api}/auth/me", token=forged).status == 401
    assert http("GET", f"{stack.api}/users", token=forged).status == 401

    # Sin firma (alg none).
    none_header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    unsigned = f"{none_header}.{payload}."
    assert http("GET", f"{stack.api}/users", token=unsigned).status == 401

    # Con el secreto real del entorno sí valida: la prueba anterior no es un falso negativo.
    genuine = _sign_hs256(claims, stack.env["JWT_SECRET"])
    stack.remember("token regenerado", genuine)
    assert http("GET", f"{stack.api}/auth/me", token=genuine).status == 200


# --- 4. Roles ------------------------------------------------------------------------


def test_el_admin_da_de_alta_miembro_y_editor(
    stack: Stack, admin: Account, member: Account, editor: Account
) -> None:
    for account in (member, editor):
        me = http("GET", f"{stack.api}/auth/me", token=account.token)
        assert me.status == 200
        assert (me.json()["username"], me.json()["role"]) == (account.username, account.role)

    listing = http("GET", f"{stack.api}/users", token=admin.token)
    assert listing.status == 200
    roles = {user["username"]: user["role"] for user in listing.json()}
    assert roles == {admin.username: "admin", member.username: "miembro", editor.username: "editor"}
    assert "password" not in listing.text
    assert "argon2" not in listing.text


def test_solo_el_admin_gestiona_usuarios(
    stack: Stack, admin: Account, member: Account, editor: Account
) -> None:
    new_user = {
        "username": f"e2e-intruso-{secrets.token_hex(3)}",
        "password": secrets.token_urlsafe(24),
        "role": "admin",
    }
    attempts = [
        ("GET", "/users", None),
        ("POST", "/users", new_user),
        ("PATCH", f"/users/{admin.id}", {"is_active": False}),
        ("PATCH", f"/users/{uuid.uuid4()}", {"role": "admin"}),
    ]
    for method, path, body in attempts:
        anonymous = http(method, f"{stack.api}{path}", json_body=body)
        assert anonymous.status == 401, (method, path)
        for account in (member, editor):
            response = http(method, f"{stack.api}{path}", json_body=body, token=account.token)
            assert response.status == 403, (account.role, method, path, response.text)

    assert stack.psql("select count(*) from users") == ["3"]
    assert stack.psql("select count(*) from users where role = 'admin'") == ["1"]


def test_nadie_se_sube_el_rol_a_si_mismo(stack: Stack, member: Account, editor: Account) -> None:
    for account in (member, editor):
        response = http(
            "PATCH",
            f"{stack.api}/users/{account.id}",
            json_body={"role": "admin"},
            token=account.token,
        )
        assert response.status == 403, response.text
        me = http("GET", f"{stack.api}/auth/me", token=account.token)
        assert me.json()["role"] == account.role
    assert stack.psql("select count(*) from audit_events where action = 'role_changed'") == ["0"]


def test_cors_solo_admite_el_origen_configurado(stack: Stack) -> None:
    def preflight(origin: str):
        return http(
            "OPTIONS",
            f"{stack.api}/auth/token",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    allowed = preflight(stack.frontend_origin)
    assert allowed.status == 200
    assert allowed.headers["access-control-allow-origin"] == stack.frontend_origin
    assert "access-control-allow-credentials" not in allowed.headers

    for origin in ("http://atacante.test", f"{stack.frontend_origin}.atacante.test", "null"):
        denied = preflight(origin)
        assert denied.status == 400, origin
        assert "access-control-allow-origin" not in denied.headers, origin
        simple = http("GET", f"{stack.api}/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in simple.headers, origin


def test_openapi_publicado_coincide_con_el_contrato_versionado(stack: Stack) -> None:
    from conftest import REPO_ROOT

    served = http("GET", f"{stack.api}/openapi.json")
    assert served.status == 200
    contract = json.loads((REPO_ROOT / "backend" / "openapi.json").read_text("utf-8"))
    assert served.json() == contract
    for secret in stack.sensitive.values():
        assert secret not in served.text


def test_cambio_de_rol_y_baja_con_el_token_vigente(
    stack: Stack, admin: Account, member: Account, editor: Account
) -> None:
    # El editor pasa a miembro: su token sigue valiendo, pero con el rol nuevo.
    changed = http(
        "PATCH",
        f"{stack.api}/users/{editor.id}",
        json_body={"role": "miembro"},
        token=admin.token,
    )
    assert changed.status == 200, changed.text
    me = http("GET", f"{stack.api}/auth/me", token=editor.token)
    assert (me.status, me.json()["role"]) == (200, "miembro")

    # El miembro se da de baja: su token deja de valer y no puede volver a entrar.
    deactivated = http(
        "PATCH",
        f"{stack.api}/users/{member.id}",
        json_body={"is_active": False},
        token=admin.token,
    )
    assert deactivated.status == 200, deactivated.text
    assert http("GET", f"{stack.api}/auth/me", token=member.token).status == 401
    assert login(stack, member.username, member.password).status == 401

    # El admin no puede dejar a la unidad sin admin.
    lockout = http(
        "PATCH", f"{stack.api}/users/{admin.id}", json_body={"is_active": False}, token=admin.token
    )
    assert lockout.status == 409


# --- 5. Auditoría --------------------------------------------------------------------


def test_la_auditoria_registra_todo_el_recorrido(
    stack: Stack, admin: Account, member: Account, editor: Account
) -> None:
    rows = [
        json.loads(line)
        for line in stack.psql("select row_to_json(a) from audit_events a order by a.id")
    ]
    assert rows, "audit_events está vacía"

    def events(action: str) -> list[dict]:
        return [row for row in rows if row["action"] == action]

    # Alta del admin por CLI: sin actor autenticado.
    cli_creation = [e for e in events("user_created") if e["target_username"] == admin.username]
    assert len(cli_creation) == 1
    assert cli_creation[0]["actor_id"] is None
    assert cli_creation[0]["actor_username"] == "cli"
    assert cli_creation[0]["details"] == {"role": "admin", "via": "cli"}

    # Altas por la API: el actor es el admin.
    for account in (member, editor):
        (creation,) = [
            e for e in events("user_created") if e["target_username"] == account.username
        ]
        assert creation["actor_username"] == admin.username
        assert creation["actor_id"] == admin.id
        assert creation["details"] == {"role": account.role, "via": "api"}

    assert {e["actor_username"] for e in events("login_success")} >= {
        admin.username,
        member.username,
        editor.username,
    }
    failure_reasons = {e["details"]["reason"] for e in events("login_failure")}
    assert {"bad_password", "unknown_user", "inactive_user"} <= failure_reasons
    assert all(e["actor_id"] is None for e in events("login_failure"))

    (role_change,) = events("role_changed")
    assert role_change["target_username"] == editor.username
    assert role_change["actor_username"] == admin.username
    assert role_change["details"] == {"from": "editor", "to": "miembro"}

    (deactivation,) = events("user_deactivated")
    assert deactivation["target_username"] == member.username
    assert deactivation["actor_username"] == admin.username

    # Los intentos rechazados (403, 409) no han cambiado nada.
    assert events("user_reactivated") == []
    assert all(row["occurred_at"] for row in rows)


def test_la_auditoria_no_guarda_contrasenas_ni_tokens(stack: Stack, admin: Account) -> None:
    dump = "\n".join(stack.psql("select row_to_json(a) from audit_events a order by a.id"))
    assert dump
    for name, secret in stack.sensitive.items():
        assert secret not in dump, f"audit_events contiene {name}"
        if secret.count(".") == 2:  # un JWT: tampoco ninguna de sus partes
            for part in secret.split("."):
                assert part not in dump, f"audit_events contiene parte de {name}"
    assert "argon2" not in dump
    assert "eyJ" not in dump


def test_los_logs_no_contienen_secretos(stack: Stack, admin: Account) -> None:
    result = stack.compose("logs", "--no-color", "--no-log-prefix", timeout=120)
    assert result.returncode == 0, result.stderr
    logs = result.stdout + result.stderr
    assert logs.strip()
    leaked = [name for name, secret in stack.sensitive.items() if secret in logs]
    assert leaked == [], f"los logs de los contenedores contienen: {leaked}"


def test_el_entorno_sigue_sano_al_terminar(stack: Stack) -> None:
    assert http("GET", f"{stack.api}/health/ready").status == 200
    services = _ps(stack)
    for name in ("postgres", "fuseki", "backend"):
        assert services[name]["Health"] == "healthy", name
    restarts = stack.compose("ps", "--all", "--format", "{{.Service}} {{.Status}}").stdout
    assert "Restarting" not in restarts
