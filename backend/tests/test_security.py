"""Pruebas de seguridad de la fase 1 (agente ``qa``).

Complementan ``test_auth.py``, ``test_users.py`` y ``test_config.py`` con los casos que
faltaban: confusión de algoritmo y cabeceras raras en el JWT, tokens vigentes tras una
baja o un cambio de rol, escalada de privilegios sobre la propia cuenta, enumeración de
usuarios en el login, contenido de la auditoría, exposición de ``/openapi.json`` y
``/docs`` y cabeceras CORS con orígenes no permitidos.

La inyección en consultas SPARQL todavía no aplica: la fase 1 no tiene ningún endpoint
que acepte consultas (el único uso de SPARQL es el ``ASK {}`` fijo de ``/health/ready``).

Todas las credenciales de este fichero son ficticias.
"""

import base64
import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import fair, security
from app.config import Settings
from app.export_openapi import OPENAPI_PATH
from app.models import AuditAction, AuditEvent, Role, User
from app.security import create_access_token
from tests.conftest import DEFAULT_PASSWORD, FIXTURE_DATA_DIR, FIXTURE_SEMANTIC_DIR, TESTS_DIR

# Decisión 50: esquemas y ontologías se publican en un catálogo (el de las pruebas).
ONTOLOGIES = "/ontologies?catalog=pruebas"
SCHEMES = "/schemes?catalog=pruebas"

_SERIES_TTL = FIXTURE_DATA_DIR / "sintetico" / "modbus-tcp-testbed.ttl"
_SCHEME_TTL = FIXTURE_SEMANTIC_DIR / "vocabularios" / "corp" / "trl.ttl"
_ONTOLOGY_TTL = FIXTURE_SEMANTIC_DIR / "ontologias" / "pqcm" / "0.4.0.ttl"


@pytest.fixture
def no_pellet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Métricas sin lanzar Java (aquí solo importa la auditoría)."""
    from app import owl_metrics, vocab_ingest

    monkeypatch.setattr(
        vocab_ingest,
        "compute_ontology_metrics",
        lambda p, _s: (
            owl_metrics.compute_metrics(p.graph, p.uri).to_dict(),
            owl_metrics.Consistency().to_dict(),
        ),
    )


ALLOWED_ORIGIN = "http://localhost:5173"  # el de CORS_ORIGINS en conftest.py
ATTACKER_SECRET = "secreto-del-atacante-no-es-el-del-servidor-000"
NEW_PASSWORD = "otra-contrasena-de-prueba"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _claims(user: User, role: str | None = None, **extra: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "sub": str(user.id),
        "username": user.username,
        "role": role or user.role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        **extra,
    }


def _raw_token(header: dict[str, Any], claims: dict[str, Any], secret: str | None) -> str:
    """Construye un JWT a mano, sin pasar por PyJWT, para poder forjar cabeceras."""
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    if secret is None:
        return f"{signing_input}."
    digest = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(digest)}"


def _all_audit_text(session_factory: sessionmaker[Session]) -> str:
    """Todas las columnas de todos los eventos de auditoría, como texto."""
    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent).order_by(AuditEvent.id)))
    return "\n".join(
        json.dumps(
            {col.name: getattr(event, col.name) for col in AuditEvent.__table__.columns},
            default=str,
            ensure_ascii=False,
        )
        for event in events
    )


# --- JWT: algoritmo cambiado ---------------------------------------------------------


@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_token_with_other_hmac_algorithm_is_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User], algorithm: str
) -> None:
    """Firma correcta con el secreto real, pero con un algoritmo que no es el configurado."""
    user = make_user("otroalg", Role.ADMIN)
    assert settings.jwt_algorithm == "HS256"
    token = jwt.encode(_claims(user), settings.jwt_secret, algorithm=algorithm)
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401
    assert client.get("/users", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("alg", ["none", "None", "NONE", "nOnE", "", "HS256 ", "hs256"])
def test_alg_none_variants_without_signature_are_rejected(
    client: TestClient, make_user: Callable[..., User], alg: str
) -> None:
    user = make_user("algnone", Role.ADMIN)
    token = _raw_token({"alg": alg, "typ": "JWT"}, _claims(user), secret=None)
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("alg", ["none", "None", "hs256", "RS256", "ES256", "PS256", "EdDSA"])
def test_alg_header_swapped_on_valid_hs256_signature_is_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User], alg: str
) -> None:
    """La firma HMAC es del secreto real, pero la cabecera declara otro algoritmo."""
    user = make_user("algswap", Role.ADMIN)
    token = _raw_token({"alg": alg, "typ": "JWT"}, _claims(user), settings.jwt_secret)
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_only_hmac_algorithms_can_be_configured() -> None:
    """Sin algoritmos asimétricos no hay confusión de clave pública como secreto HMAC."""
    annotation = Settings.model_fields["jwt_algorithm"].annotation
    assert set(annotation.__args__) == {"HS256", "HS384", "HS512"}  # type: ignore[union-attr]


# --- JWT: kid y otras cabeceras ------------------------------------------------------


@pytest.mark.parametrize(
    "extra_header",
    [
        {"kid": "../../../../dev/null"},
        {"kid": "' OR '1'='1"},
        {"kid": "clave-del-atacante"},
        {"jku": "http://atacante.test/jwks.json"},
        {"x5u": "http://atacante.test/cert.pem"},
        {
            "jwk": {
                "kty": "oct",
                "k": _b64(ATTACKER_SECRET.encode()),
            }
        },
    ],
    ids=["kid-path", "kid-sqli", "kid-otro", "jku", "x5u", "jwk-embebida"],
)
def test_key_selection_headers_do_not_change_the_key(
    client: TestClient,
    settings: Settings,
    make_user: Callable[..., User],
    extra_header: dict[str, Any],
) -> None:
    """``kid``, ``jku``, ``x5u`` y ``jwk`` no hacen que el servidor use otra clave.

    Firmado con la clave del atacante se rechaza siempre. Firmado con el secreto real se
    acepta: la cabecera se ignora, y eso es lo que demuestra que no selecciona la clave.
    """
    user = make_user("cabeceras", Role.ADMIN)
    header = {"alg": "HS256", "typ": "JWT", **extra_header}

    forged = _raw_token(header, _claims(user), ATTACKER_SECRET)
    assert client.get("/auth/me", headers=_bearer(forged)).status_code == 401
    assert client.get("/users", headers=_bearer(forged)).status_code == 401

    genuine = _raw_token(header, _claims(user), settings.jwt_secret)
    assert client.get("/auth/me", headers=_bearer(genuine)).status_code == 200


@pytest.mark.parametrize(
    "header",
    [
        {"typ": "JWT"},
        {"alg": ["HS256"], "typ": "JWT"},
        {"alg": None, "typ": "JWT"},
        {"alg": 256, "typ": "JWT"},
        {"alg": "HS256", "kid": {"a": 1}},
        {"alg": "HS256", "kid": 7},
    ],
    ids=["sin-alg", "alg-lista", "alg-null", "alg-numero", "kid-objeto", "kid-numero"],
)
def test_malformed_headers_give_401_not_500(
    client: TestClient, settings: Settings, make_user: Callable[..., User], header: dict[str, Any]
) -> None:
    user = make_user("rara", Role.ADMIN)
    token = _raw_token(header, _claims(user), settings.jwt_secret)
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        "a.b",
        "a.b.c.d",
        "a.b.c.d.e",  # forma de un JWE
        "..",
        "eyJhbGciOiJIUzI1NiJ9..",
        "x" * 20_000,
        ("e" * 8000) + "." + ("e" * 8000) + "." + ("e" * 8000),
    ],
    ids=["dos-partes", "cuatro-partes", "jwe", "vacias", "solo-cabecera", "largo", "largo-3"],
)
def test_garbage_tokens_give_401_not_500(client: TestClient, token: str) -> None:
    response = client.get("/auth/me", headers=_bearer(token))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_header_and_payload_must_be_json_objects(client: TestClient, settings: Settings) -> None:
    for header, payload in [(b"[]", b"{}"), (b'{"alg":"HS256"}', b"[]"), (b'"x"', b'"y"')]:
        signing_input = f"{_b64(header)}.{_b64(payload)}"
        digest = hmac.new(
            settings.jwt_secret.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        token = f"{signing_input}.{_b64(digest)}"
        assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


# --- JWT: claims ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"role": "superadmin"},
        {"role": "lector"},
        {"role": "ADMIN"},
        {"role": ["admin"]},
        {"role": None},
        {"sub": None},
        {"sub": 12345},
        {"sub": ""},
        {"sub": "00000000-0000-0000-0000-00000000000"},
        {"exp": "mañana"},
        {"exp": None},
        {"iat": "ayer"},
    ],
    ids=lambda o: f"{next(iter(o))}={next(iter(o.values()))!r}",
)
def test_tokens_with_invalid_claims_are_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User], overrides: dict
) -> None:
    user = make_user("claims", Role.ADMIN)
    token = _raw_token(
        {"alg": "HS256", "typ": "JWT"}, {**_claims(user), **overrides}, settings.jwt_secret
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("missing", ["sub", "exp", "iat", "role"])
def test_tokens_without_a_required_claim_are_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User], missing: str
) -> None:
    user = make_user("faltan", Role.ADMIN)
    claims = _claims(user)
    del claims[missing]
    token = _raw_token({"alg": "HS256", "typ": "JWT"}, claims, settings.jwt_secret)
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_token_not_yet_valid_is_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User]
) -> None:
    user = make_user("futuro", Role.ADMIN)
    nbf = int((datetime.now(UTC) + timedelta(minutes=3)).timestamp())
    token = jwt.encode(_claims(user, nbf=nbf), settings.jwt_secret, algorithm="HS256")
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_token_expired_one_second_ago_is_rejected(
    client: TestClient, settings: Settings, make_user: Callable[..., User]
) -> None:
    """No hay margen de gracia (leeway) tras la caducidad."""
    user = make_user("justo", Role.ADMIN)
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        _claims(user, iat=now - 600, exp=now - 1), settings.jwt_secret, algorithm="HS256"
    )
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_role_claim_in_token_never_grants_privileges(
    client: TestClient, settings: Settings, make_user: Callable[..., User]
) -> None:
    """Un token bien firmado que dice ``admin`` no vale más que el rol guardado en la BD.

    Es el caso de un token emitido cuando la cuenta era admin y que sigue vigente tras
    degradarla, o de una fuga del secreto limitada a un usuario sin privilegios.
    """
    user = make_user("degradado", Role.MIEMBRO)
    token, _ = create_access_token(
        settings, user_id=user.id, username=user.username, role=Role.ADMIN
    )
    me = client.get("/auth/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["role"] == "miembro"
    assert client.get("/users", headers=_bearer(token)).status_code == 403
    assert (
        client.post(
            "/users",
            json={"username": "nuevo", "password": NEW_PASSWORD, "role": "admin"},
            headers=_bearer(token),
        ).status_code
        == 403
    )


def test_username_claim_is_not_used_to_identify_the_account(
    client: TestClient, settings: Settings, make_user: Callable[..., User]
) -> None:
    make_user("jefa", Role.ADMIN)
    member = make_user("peon", Role.MIEMBRO)
    token, _ = create_access_token(settings, user_id=member.id, username="jefa", role=Role.ADMIN)
    me = client.get("/auth/me", headers=_bearer(token))
    assert me.json()["username"] == "peon"
    assert client.get("/users", headers=_bearer(token)).status_code == 403


# --- JWT: baja o cambio de rol con el token vigente ----------------------------------


def test_deactivated_user_token_is_rejected_everywhere(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
) -> None:
    make_user("admin1", Role.ADMIN)
    admin_headers = login("admin1")
    other = make_user("admin2", Role.ADMIN)
    other_headers = login("admin2")
    assert client.get("/users", headers=other_headers).status_code == 200

    response = client.patch(f"/users/{other.id}", json={"is_active": False}, headers=admin_headers)
    assert response.status_code == 200

    assert client.get("/auth/me", headers=other_headers).status_code == 401
    assert client.get("/users", headers=other_headers).status_code == 401
    assert (
        client.post(
            "/users",
            json={"username": "nuevo", "password": NEW_PASSWORD, "role": "admin"},
            headers=other_headers,
        ).status_code
        == 401
    )
    # Tampoco puede reactivarse a sí mismo con el token antiguo.
    assert (
        client.patch(
            f"/users/{other.id}", json={"is_active": True}, headers=other_headers
        ).status_code
        == 401
    )


def test_promotion_and_demotion_apply_to_the_token_in_use(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
) -> None:
    make_user("admin1", Role.ADMIN)
    admin_headers = login("admin1")
    target = make_user("sube-y-baja", Role.MIEMBRO)
    target_headers = login("sube-y-baja")
    assert client.get("/users", headers=target_headers).status_code == 403

    # Fase 4 (decisión 18): un cambio de rol invalida los tokens emitidos antes, así que
    # el token en uso deja de valer (401) y el rol nuevo llega con un login nuevo.
    client.patch(f"/users/{target.id}", json={"role": "admin"}, headers=admin_headers)
    assert client.get("/users", headers=target_headers).status_code == 401
    target_headers = login("sube-y-baja")
    assert client.get("/users", headers=target_headers).status_code == 200
    assert client.get("/auth/me", headers=target_headers).json()["role"] == "admin"

    client.patch(f"/users/{target.id}", json={"role": "editor"}, headers=admin_headers)
    assert client.get("/users", headers=target_headers).status_code == 401
    target_headers = login("sube-y-baja")
    assert client.get("/users", headers=target_headers).status_code == 403
    assert client.get("/auth/me", headers=target_headers).json()["role"] == "editor"


# --- Dónde se acepta el token --------------------------------------------------------


def test_token_is_only_accepted_in_the_authorization_header(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
) -> None:
    make_user("donde", Role.ADMIN)
    token = login("donde")["Authorization"].removeprefix("Bearer ")

    assert client.get("/users", params={"access_token": token}).status_code == 401
    assert client.get("/users", params={"token": token}).status_code == 401
    assert client.get("/users", headers={"Cookie": f"access_token={token}"}).status_code == 401
    assert client.get("/users", headers={"X-Access-Token": token}).status_code == 401
    for scheme in ("Basic", "Token", "JWT", "Digest"):
        response = client.get("/users", headers={"Authorization": f"{scheme} {token}"})
        assert response.status_code == 401, scheme
    assert client.get("/users", headers={"Authorization": token}).status_code == 401


# --- Escalada de privilegios ---------------------------------------------------------


@pytest.mark.parametrize("role", [Role.MIEMBRO, Role.EDITOR])
@pytest.mark.parametrize(
    "payload",
    [{"role": "admin"}, {"role": "editor"}, {"is_active": True}, {"role": "admin", "x": 1}],
    ids=["a-admin", "a-editor", "is-active", "campo-extra"],
)
def test_non_admin_cannot_patch_their_own_account(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
    role: Role,
    payload: dict[str, Any],
) -> None:
    user = make_user("ambicioso", role)
    response = client.patch(f"/users/{user.id}", json=payload, headers=login("ambicioso"))
    assert response.status_code == 403

    with session_factory() as session:
        stored = session.get(User, user.id)
        assert stored is not None
        assert stored.role is role
        actions = set(session.scalars(select(AuditEvent.action)))
    assert actions == {AuditAction.LOGIN_SUCCESS}


@pytest.mark.parametrize("role", [Role.MIEMBRO, Role.EDITOR])
def test_non_admin_cannot_touch_an_admin_account(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
    role: Role,
) -> None:
    admin = make_user("admin1", Role.ADMIN)
    make_user("ambicioso", role)
    headers = login("ambicioso")

    for payload in ({"is_active": False}, {"role": "miembro"}):
        assert client.patch(f"/users/{admin.id}", json=payload, headers=headers).status_code == 403

    with session_factory() as session:
        stored = session.get(User, admin.id)
        assert stored is not None
        assert stored.role is Role.ADMIN
        assert stored.is_active is True


@pytest.mark.parametrize("role", [Role.MIEMBRO, Role.EDITOR])
def test_forbidden_does_not_reveal_whether_an_account_exists(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    role: Role,
) -> None:
    """Un no-admin recibe el mismo 403 para un id que existe y para uno que no."""
    existing = make_user("existe", Role.MIEMBRO)
    make_user("curioso", role)
    headers = login("curioso")

    real = client.patch(f"/users/{existing.id}", json={"role": "editor"}, headers=headers)
    ghost = client.patch(f"/users/{uuid.uuid4()}", json={"role": "editor"}, headers=headers)
    assert real.status_code == ghost.status_code == 403
    assert real.json() == ghost.json()


@pytest.mark.parametrize(
    "extra",
    [
        {"is_active": True},
        {"id": "00000000-0000-0000-0000-000000000001"},
        {"password_hash": "$argon2id$v=19$m=8,t=1,p=1$AAAA$AAAA"},
        {"created_at": "2000-01-01T00:00:00Z"},
    ],
    ids=lambda e: next(iter(e)),
)
def test_create_user_rejects_fields_outside_the_contract(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    extra: dict[str, Any],
) -> None:
    make_user("admin1", Role.ADMIN)
    body = {"username": "nuevo", "password": NEW_PASSWORD, "role": "miembro", **extra}
    assert client.post("/users", json=body, headers=login("admin1")).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"username": "otro-nombre"},
        {"password": NEW_PASSWORD},
        {"password_hash": "$argon2id$v=19$m=8,t=1,p=1$AAAA$AAAA"},
        {"id": "00000000-0000-0000-0000-000000000001"},
    ],
    ids=lambda e: next(iter(e)),
)
def test_update_user_rejects_fields_outside_the_contract(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
    extra: dict[str, Any],
) -> None:
    make_user("admin1", Role.ADMIN)
    target = make_user("objetivo", Role.MIEMBRO)
    original_hash = target.password_hash
    response = client.patch(
        f"/users/{target.id}", json={"role": "editor", **extra}, headers=login("admin1")
    )
    assert response.status_code == 422
    with session_factory() as session:
        stored = session.get(User, target.id)
        assert stored is not None
        assert (stored.username, stored.role, stored.password_hash) == (
            "objetivo",
            Role.MIEMBRO,
            original_hash,
        )


def test_role_lector_cannot_be_assigned(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
) -> None:
    """``lector`` es el anónimo: no existe como rol de una cuenta."""
    make_user("admin1", Role.ADMIN)
    headers = login("admin1")
    target = make_user("objetivo", Role.MIEMBRO)
    body = {"username": "nuevo", "password": NEW_PASSWORD, "role": "lector"}
    assert client.post("/users", json=body, headers=headers).status_code == 422
    for role in ("lector", "root", "", "Admin"):
        response = client.patch(f"/users/{target.id}", json={"role": role}, headers=headers)
        assert response.status_code == 422, role


def test_user_responses_never_include_password_material(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
) -> None:
    make_user("admin1", Role.ADMIN)
    headers = login("admin1")
    created = client.post(
        "/users",
        json={"username": "nuevo", "password": NEW_PASSWORD, "role": "miembro"},
        headers=headers,
    )
    assert created.status_code == 201
    patched = client.patch(
        f"/users/{created.json()['id']}", json={"role": "editor"}, headers=headers
    )
    listed = client.get("/users", headers=headers)
    me = client.get("/auth/me", headers=headers)
    expected_fields = {"id", "username", "role", "is_active", "created_at", "updated_at"}
    assert set(created.json()) == set(patched.json()) == set(me.json()) == expected_fields
    for response in (created, patched, listed, me):
        assert "argon2" not in response.text
        assert "password" not in response.text
        assert NEW_PASSWORD not in response.text
        assert DEFAULT_PASSWORD not in response.text


# --- Enumeración de usuarios en el login ---------------------------------------------


def test_login_failures_are_indistinguishable(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """Usuario inexistente, contraseña mala y cuenta de baja: misma respuesta exacta."""
    make_user("activa")
    make_user("de-baja", is_active=False)
    attempts = [
        ("no-existe", DEFAULT_PASSWORD),
        ("activa", "contrasena-incorrecta"),
        ("de-baja", DEFAULT_PASSWORD),
        ("de-baja", "contrasena-incorrecta"),
        ("ACTIVA", DEFAULT_PASSWORD),
        ("activa ", DEFAULT_PASSWORD),
    ]
    responses = [
        client.post("/auth/token", data={"username": u, "password": p}) for u, p in attempts
    ]
    first = responses[0]
    assert first.status_code == 401
    for (username, _), response in zip(attempts, responses, strict=True):
        assert response.status_code == first.status_code, username
        assert response.content == first.content, username
        assert dict(response.headers) == dict(first.headers), username
        assert username not in response.text


def test_login_always_runs_the_password_hash(
    client: TestClient, make_user: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con usuario inexistente o de baja se verifica igualmente un hash argon2.

    Es la comprobación determinista de que el tiempo de respuesta no delata qué cuentas
    existen; ``test_login_timing_does_not_reveal_accounts`` lo mide de verdad.
    """
    make_user("activa")
    make_user("de-baja", is_active=False)
    calls: list[str] = []
    real_verify = security._password_hash.verify

    def spy(password: str, password_hash: str) -> bool:
        calls.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(security._password_hash, "verify", spy)

    for username in ("no-existe", "activa", "de-baja"):
        calls.clear()
        client.post("/auth/token", data={"username": username, "password": "x" * 16})
        assert len(calls) == 1, username
        assert calls[0].startswith("$argon2id$"), username


def test_production_password_hash_is_argon2id_with_its_default_cost(
    production_password_hash: None,
) -> None:
    """En producción, argon2id con 64 MiB, 3 pasadas y 4 hilos (las pruebas usan un coste
    mínimo; ver ``conftest.py``)."""
    password_hash = security.hash_password(DEFAULT_PASSWORD)
    assert password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert security.verify_password(DEFAULT_PASSWORD, password_hash)
    assert not security.verify_password("otra-contrasena-larga", password_hash)


def test_dummy_hash_costs_the_same_as_a_real_one(production_password_hash: None) -> None:
    """El hash de relleno usa los mismos parámetros argon2 que una contraseña real."""

    def params(password_hash: str) -> tuple[str, ...]:
        _, variant, version, cost, salt, digest = password_hash.split("$")
        return variant, version, cost, str(len(salt)), str(len(digest))

    assert params(security._DUMMY_HASH) == params(security.hash_password(DEFAULT_PASSWORD))


def test_login_timing_does_not_reveal_accounts(
    client: TestClient, make_user: Callable[..., User], production_password_hash: None
) -> None:
    """Medición gruesa: el login de un usuario inexistente no es mucho más rápido.

    El umbral es amplio (la mitad) para que no falle por ruido; lo que detecta es que
    alguien quite la verificación de relleno, que haría la respuesta ~100 veces más rápida.
    """
    import statistics
    import time

    make_user("activa")

    def measure(username: str) -> float:
        samples = []
        for _ in range(7):
            start = time.perf_counter()
            client.post("/auth/token", data={"username": username, "password": "x" * 16})
            samples.append(time.perf_counter() - start)
        return statistics.median(samples)

    measure("activa")  # calentamiento
    existing = measure("activa")
    unknown = measure("no-existe")
    assert unknown > existing * 0.5, f"inexistente={unknown:.4f}s existente={existing:.4f}s"
    assert existing > unknown * 0.5, f"inexistente={unknown:.4f}s existente={existing:.4f}s"


@pytest.mark.parametrize(
    "username",
    ["a" * 10_000, "admin'--", "admin' OR '1'='1", '"; DROP TABLE users; --', "ñandú"],
    ids=["largo", "comentario-sql", "or-sql", "drop", "unicode"],
)
def test_login_with_hostile_username_is_a_plain_401(
    client: TestClient,
    make_user: Callable[..., User],
    session_factory: sessionmaker[Session],
    username: str,
) -> None:
    make_user("admin", Role.ADMIN)
    response = client.post("/auth/token", data={"username": username, "password": DEFAULT_PASSWORD})
    assert response.status_code == 401
    assert "access_token" not in response.text
    with session_factory() as session:
        event = session.scalars(select(AuditEvent)).one()
        assert session.scalars(select(User)).one().username == "admin"
    assert event.action == AuditAction.LOGIN_FAILURE
    assert event.target_username == username[:64]
    assert event.target_user_id is None


@pytest.mark.parametrize(
    "username",
    [
        "admin\x00",
        "\x00",
        "ad\x00min",
        "ad\tmin",
        "admin\n",
        "admin\r\nx",
        "ad\x1bmin",
        "ad\x7fmin",
    ],
    ids=["nul-final", "solo-nul", "nul-medio", "tabulador", "lf", "crlf", "escape", "del"],
)
def test_login_with_control_chars_is_the_generic_401_and_is_not_stored(
    client: TestClient,
    make_user: Callable[..., User],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    username: str,
) -> None:
    """NUL y demás caracteres de control: mismo 401 que un usuario inexistente.

    PostgreSQL rechaza el NUL en un texto, así que el valor no debe llegar a la consulta
    ni a la auditoría. La verificación argon2 se ejecuta igualmente (mismo tiempo).
    """
    make_user("admin", Role.ADMIN)
    reference = client.post(
        "/auth/token", data={"username": "no-existe", "password": DEFAULT_PASSWORD}
    )

    verified: list[str] = []
    real_verify = security._password_hash.verify

    def spy(password: str, password_hash: str) -> bool:
        verified.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(security._password_hash, "verify", spy)
    response = client.post("/auth/token", data={"username": username, "password": DEFAULT_PASSWORD})

    assert response.status_code == 401
    assert response.content == reference.content
    assert dict(response.headers) == dict(reference.headers)
    assert len(verified) == 1

    with session_factory() as session:
        event = list(session.scalars(select(AuditEvent).order_by(AuditEvent.id)))[-1]
    assert event.action == AuditAction.LOGIN_FAILURE
    assert event.details == {"reason": "invalid_username"}
    # Fase 4 (decisión 18): se guarda el nombre intentado sin caracteres de control (nunca
    # el valor bruto con NUL), truncado a 64.
    expected = "".join(c for c in username if unicodedata.category(c) != "Cc")[:64]
    assert event.target_username == (expected or None)
    assert event.target_user_id is None
    assert event.actor_id is None


def test_login_ignores_client_supplied_scope_and_grant(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """Pedir ``scope=admin`` en el formulario OAuth2 no cambia el rol del token."""
    make_user("modesto", Role.MIEMBRO)
    response = client.post(
        "/auth/token",
        data={
            "username": "modesto",
            "password": DEFAULT_PASSWORD,
            "scope": "admin editor",
            "role": "admin",
            "grant_type": "password",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "miembro"
    assert client.get("/users", headers=_bearer(body["access_token"])).status_code == 403


def test_login_does_not_accept_credentials_in_the_query_string(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """Las credenciales en la URL acabarían en los logs de acceso."""
    make_user("urlera")
    response = client.post(
        "/auth/token", params={"username": "urlera", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 422
    assert (
        client.get(
            "/auth/token", params={"username": "urlera", "password": DEFAULT_PASSWORD}
        ).status_code
        == 405
    )


SENSITIVE_VALUE = "valor-secreto-que-no-debe-volver"


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("POST", "/users", {"json": {"username": "nuevo", "password": SENSITIVE_VALUE[:11]}}),
        (
            "POST",
            "/users",
            {"json": {"username": "nuevo", "password": SENSITIVE_VALUE, "role": "lector"}},
        ),
        (
            "POST",
            "/users",
            {"json": {"username": "nuevo", "password": SENSITIVE_VALUE + "\x00", "role": "editor"}},
        ),
        (
            "POST",
            "/users",
            {
                "json": {
                    "username": "nuevo",
                    "password": SENSITIVE_VALUE,
                    "role": "editor",
                    "extra": SENSITIVE_VALUE,
                }
            },
        ),
        ("POST", "/users", {"json": {"username": "nuevo", "password": {"x": SENSITIVE_VALUE}}}),
        ("POST", "/users", {"json": {"username": "nuevo", "password": SENSITIVE_VALUE * 20}}),
        (
            "POST",
            "/users",
            {
                "content": b'{"username": "nuevo", "password": "' + SENSITIVE_VALUE.encode() + b'"',
                "headers": {"Content-Type": "application/json"},
            },
        ),
        ("POST", "/users", {"json": [SENSITIVE_VALUE]}),
        ("PATCH", "/users/{id}", {"json": {"role": SENSITIVE_VALUE}}),
        ("PATCH", "/users/{id}", {"json": {"password": SENSITIVE_VALUE}}),
        ("POST", "/auth/token", {"data": {"password": SENSITIVE_VALUE}}),
        ("POST", "/auth/token", {"json": {"username": "x", "password": SENSITIVE_VALUE}}),
    ],
    ids=[
        "corta",
        "rol-malo",
        "nul-en-password",
        "campo-extra",
        "password-objeto",
        "larga",
        "json-roto",
        "lista",
        "patch-rol",
        "patch-password",
        "login-sin-usuario",
        "login-json",
    ],
)
def test_validation_errors_do_not_echo_the_values_sent(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    method: str,
    path: str,
    kwargs: dict[str, Any],
) -> None:
    """Un 422 solo lleva ``type``, ``loc`` y ``msg``: nunca el valor enviado."""
    admin = make_user("admin1", Role.ADMIN)
    headers = {**login("admin1"), **kwargs.pop("headers", {})}
    response = client.request(method, path.format(id=admin.id), headers=headers, **kwargs)
    assert response.status_code == 422, response.text
    assert SENSITIVE_VALUE[:11] not in response.text
    errors = response.json()["detail"]
    assert errors
    for error in errors:
        assert set(error) <= {"type", "loc", "msg"}, error


def test_create_user_rejects_control_chars_in_username_and_password(
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    make_user("admin1", Role.ADMIN)
    headers = login("admin1")
    for field_name, value in [
        ("username", "nue\x00vo"),
        ("username", "nuevo\n"),
        ("password", NEW_PASSWORD + "\x00"),
        ("password", "con\ttabulador-larga"),
    ]:
        body = {"username": "nuevo", "password": NEW_PASSWORD, "role": "miembro", field_name: value}
        response = client.post("/users", json=body, headers=headers)
        assert response.status_code == 422, (field_name, value)
    with session_factory() as session:
        assert [u.username for u in session.scalars(select(User))] == ["admin1"]


# --- La auditoría no guarda contraseñas ni tokens ------------------------------------


@pytest.mark.usefixtures("synthetic_themes")
def test_audit_never_stores_passwords_tokens_or_hashes(
    no_pellet: None,
    client: TestClient,
    settings: Settings,
    make_user: Callable[..., User],
    session_factory: sessionmaker[Session],
) -> None:
    """Recorre todas las acciones auditadas y busca material sensible en todas las columnas."""
    admin_password = "contrasena-del-admin-auditada"
    wrong_password = "contrasena-equivocada-auditada"
    make_user("admin1", Role.ADMIN, password=admin_password)

    client.post("/auth/token", data={"username": "admin1", "password": wrong_password})
    client.post("/auth/token", data={"username": "no-existe", "password": wrong_password})
    token = client.post(
        "/auth/token", data={"username": "admin1", "password": admin_password}
    ).json()["access_token"]
    headers = _bearer(token)

    created = client.post(
        "/users",
        json={"username": "nuevo", "password": NEW_PASSWORD, "role": "miembro"},
        headers=headers,
    ).json()
    client.post(
        "/users",
        json={"username": "nuevo", "password": NEW_PASSWORD, "role": "miembro"},
        headers=headers,
    )
    client.patch(f"/users/{created['id']}", json={"role": "editor"}, headers=headers)
    client.patch(f"/users/{created['id']}", json={"is_active": False}, headers=headers)
    client.post("/auth/token", data={"username": "nuevo", "password": NEW_PASSWORD})
    client.patch(f"/users/{created['id']}", json={"is_active": True}, headers=headers)
    member_token = client.post(
        "/auth/token", data={"username": "nuevo", "password": NEW_PASSWORD}
    ).json()["access_token"]
    # Publicación de un dataset (admin hereda los permisos de editor).
    published = client.post(
        "/datasets",
        content=_SERIES_TTL.read_bytes(),
        headers=headers | {"Content-Type": "text/turtle"},
    )
    assert published.status_code == 201, published.text
    # Fase 3: publicación de un esquema SKOS y de una versión de ontología.
    scheme = client.post(
        SCHEMES,
        content=_SCHEME_TTL.read_bytes(),
        headers=headers | {"Content-Type": "text/turtle"},
    )
    assert scheme.status_code == 201, scheme.text
    ontology = client.post(
        ONTOLOGIES,
        content=_ONTOLOGY_TTL.read_bytes(),
        headers=headers | {"Content-Type": "text/turtle"},
    )
    assert ontology.status_code == 201, ontology.text
    # Decisión 49: CRUD de catálogos y datasets.
    crud = [
        client.post(
            "/catalogs",
            json={"slug": "auditado", "title": "T", "description": "D", "publisher_name": "P"},
            headers=headers,
        ),
        client.patch("/catalogs/auditado", json={"title": "T2"}, headers=headers),
        client.post(
            "/catalogs/auditado/datasets",
            json={"slug": "auditada", "title": "T", "description": "D"},
            headers=headers,
        ),
        client.patch("/datasets/auditada", json={"title": "T2"}, headers=headers),
        client.delete("/datasets/auditada", headers=headers),
        client.delete("/catalogs/auditado", headers=headers),
    ]
    assert [r.status_code for r in crud] == [201, 200, 201, 200, 204, 204]
    # Decisión 50: edición, traslado y baja de un esquema y de una ontología.
    vocab_crud = [
        client.patch("/schemes/corp/trl", json={"title": "T2"}, headers=headers),
        client.patch("/ontologies/pqcm", json={"catalog": "sintetico"}, headers=headers),
        client.delete("/schemes/corp/trl", headers=headers),
        client.delete("/ontologies/pqcm", headers=headers),
    ]
    assert [r.status_code for r in vocab_crud] == [200, 200, 204, 204], [r.text for r in vocab_crud]
    # Fase 4: fichero de distribución (subida y descarga restringida), evaluación FAIR,
    # consultas guardadas y bloqueo de login.
    member = _bearer(member_token)
    file_path = "/datasets/modbus-tcp-testbed/versions/2.1.0/distributions/csv/file"
    uploaded = client.put(file_path, files={"file": ("f.csv", b"a,b\r\n")}, headers=headers)
    assert uploaded.status_code == 201, uploaded.text
    downloaded = client.get("/dataset/modbus-tcp-testbed/2.1.0/csv/fichero", headers=member)
    assert downloaded.status_code == 200
    report = json.loads((TESTS_DIR / "fixtures" / "fuji" / "evaluate-respuesta.json").read_text())
    settings.fuji_username, settings.fuji_password = "usuario-fuji", "clave-fuji-de-prueba"
    fuji = fair.FujiClient(
        settings, transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=report))
    )
    assert fair.process_pending(session_factory, settings, fuji) >= 1
    saved = client.post(
        "/sparql/queries", json={"title": "Mía", "query": "ASK {}"}, headers=member
    ).json()
    assert client.delete(f"/sparql/queries/{saved['id']}", headers=member).status_code == 204
    for _ in range(settings.login_max_failures):
        client.post("/auth/token", data={"username": "bloqueada", "password": wrong_password})

    with session_factory() as session:
        actions = set(session.scalars(select(AuditEvent.action)))
        hashes = list(session.scalars(select(User.password_hash)))
    assert actions == {action.value for action in AuditAction}, "falta alguna acción por auditar"

    audit_text = _all_audit_text(session_factory)
    for secret in (admin_password, wrong_password, NEW_PASSWORD, settings.jwt_secret):
        assert secret not in audit_text
    for issued in (token, member_token):
        assert issued not in audit_text
        for part in issued.split("."):
            assert part not in audit_text
    for password_hash in hashes:
        assert password_hash not in audit_text
    assert "argon2" not in audit_text
    assert "eyJ" not in audit_text
    # ``bad_password`` es el motivo del fallo, no una contraseña.
    without_reasons = audit_text.replace('"reason": "bad_password"', "")
    assert not re.search(r"pass|contrase|secret|token|bearer", without_reasons, re.IGNORECASE)


@pytest.mark.usefixtures("synthetic_themes")
def test_audit_details_have_only_the_expected_keys(
    no_pellet: None,
    client: TestClient,
    make_user: Callable[..., User],
    login: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    """Lista cerrada de claves en ``details``: una clave nueva obliga a revisar esta prueba."""
    make_user("admin1", Role.ADMIN)
    headers = login("admin1")
    client.post("/auth/token", data={"username": "admin1", "password": "contrasena-mala-x"})
    created = client.post(
        "/users",
        json={"username": "nuevo", "password": NEW_PASSWORD, "role": "miembro"},
        headers=headers,
    ).json()
    client.patch(
        f"/users/{created['id']}", json={"role": "editor", "is_active": False}, headers=headers
    )
    client.post(
        "/datasets",
        content=_SERIES_TTL.read_bytes(),
        headers=headers | {"Content-Type": "text/turtle"},
    )
    for path, ttl in ((SCHEMES, _SCHEME_TTL), (ONTOLOGIES, _ONTOLOGY_TTL)):
        response = client.post(
            path, content=ttl.read_bytes(), headers=headers | {"Content-Type": "text/turtle"}
        )
        assert response.status_code == 201, response.text

    allowed = {
        AuditAction.SCHEME_PUBLISHED: {
            "scheme",
            "slug",
            "corp",
            "graph",
            "concepts",
            "triples",
            "created",
            "changed",
            "catalog",
            "via",
        },
        AuditAction.ONTOLOGY_PUBLISHED: {
            "ontology",
            "slug",
            "version",
            "version_iri",
            "graph",
            "triples",
            "created",
            "changed",
            "metrics_recomputed",
            "consistent",
            "catalog",
            "via",
        },
        AuditAction.DATASET_PUBLISHED: {
            "series",
            "slug",
            "catalog",
            "graph",
            "versions",
            "triples",
            "created",
            "changed",
            "new_versions",
            "via",
        },
        # Fase 4.
        AuditAction.DISTRIBUTION_UPLOADED: {
            "storage_key",
            "distribution",
            "media_type",
            "byte_size",
            "sha256",
            "via",
        },
        AuditAction.DISTRIBUTION_DOWNLOADED: {"storage_key", "via"},
        AuditAction.FAIR_EVALUATED: {"evaluation", "version", "status", "evaluated_url", "total"},
        AuditAction.SAVED_QUERY_CREATED: {"query"},
        AuditAction.SAVED_QUERY_DELETED: {"query"},
        AuditAction.LOGIN_LOCKED: {"failures", "minutes"},
        AuditAction.LOGIN_SUCCESS: set(),
        AuditAction.LOGIN_FAILURE: {"reason"},
        AuditAction.USER_CREATED: {"role", "via"},
        AuditAction.ROLE_CHANGED: {"from", "to"},
        AuditAction.USER_DEACTIVATED: set(),
        AuditAction.USER_REACTIVATED: set(),
        # Decisión 49.
        AuditAction.CATALOG_CREATED: {"catalog", "slug", "via"},
        AuditAction.CATALOG_UPDATED: {"catalog", "fields", "changed", "via"},
        AuditAction.CATALOG_WITHDRAWN: {"catalog", "slug", "via"},
        AuditAction.DATASET_CREATED: {"series", "slug", "catalog", "via"},
        AuditAction.DATASET_UPDATED: {
            "series",
            "fields",
            "catalog",
            "moved_from",
            "changed",
            "via",
        },
        AuditAction.DATASET_WITHDRAWN: {
            "series",
            "slug",
            "catalogs",
            "versions",
            "files_deleted",
            "files_not_deleted",
            "via",
        },
        # Decisión 50.
        AuditAction.SCHEME_UPDATED: {"scheme", "fields", "catalog", "moved_from", "changed", "via"},
        AuditAction.ONTOLOGY_UPDATED: {
            "ontology",
            "fields",
            "catalog",
            "moved_from",
            "changed",
            "via",
        },
        AuditAction.SCHEME_WITHDRAWN: {
            "scheme",
            "slug",
            "corp",
            "catalogs",
            "concepts",
            "prefix",
            "via",
        },
        AuditAction.ONTOLOGY_WITHDRAWN: {
            "ontology",
            "slug",
            "catalogs",
            "versions",
            "prefix",
            "via",
        },
    }
    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))
    assert len(events) >= 5
    for event in events:
        assert set(event.details) <= allowed[AuditAction(event.action)], event.action


def test_failed_login_audit_truncates_the_username(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """El nombre que se copia a la auditoría se corta a 64 caracteres."""
    client.post("/auth/token", data={"username": "u" * 500, "password": DEFAULT_PASSWORD})
    with session_factory() as session:
        event = session.scalars(select(AuditEvent)).one()
    assert event.target_username == "u" * 64


# --- /openapi.json y /docs -----------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _schemas_to_check(client: TestClient) -> dict[str, str]:
    return {
        "GET /openapi.json": client.get("/openapi.json").text,
        "backend/openapi.json": OPENAPI_PATH.read_text(encoding="utf-8"),
    }


def test_openapi_does_not_expose_configuration_or_secrets(
    client: TestClient, settings: Settings
) -> None:
    for name, text in _schemas_to_check(client).items():
        assert settings.jwt_secret not in text, name
        assert settings.database_url not in text or settings.database_url == "", name
        for needle in (
            "password_hash",
            "argon2",
            "JWT_SECRET",
            "jwt_secret",
            "DATABASE_URL",
            "database_url",
            "postgresql",
            "sqlite",
            "fuseki",
            "claude.ai",
            "placeholder-only-for-openapi-export",
            "test-secret",
        ):
            assert needle not in text, f"{name}: aparece {needle!r}"
        assert not _EMAIL.search(text), name
        assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}", text), name


def test_openapi_has_no_hardcoded_servers_or_contact(client: TestClient) -> None:
    """Sin ``servers`` ni ``contact``: ni dominios escritos a mano ni datos personales."""
    for name, text in _schemas_to_check(client).items():
        schema = json.loads(text)
        assert "servers" not in schema, name
        assert set(schema["info"]) <= {"title", "description", "version"}, name
        urls = set(re.findall(r"https?://[^\s\"'<>)]+", text))
        assert urls == set(), f"{name}: URLs absolutas {urls}"


def test_openapi_password_only_appears_as_input(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    schemas = schema["components"]["schemas"]
    with_password = {
        name for name, body in schemas.items() if "password" in body.get("properties", {})
    }
    assert with_password == {"UserCreate", "Body_login_auth_token_post"}
    assert set(schemas["UserRead"]["properties"]) == {
        "id",
        "username",
        "role",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert set(schemas["Token"]["properties"]) == {
        "access_token",
        "token_type",
        "expires_in",
        "role",
    }
    for body in schemas.values():
        for prop in body.get("properties", {}).values():
            assert "default" not in prop or "password" not in str(prop.get("title", "")).lower()
            assert "example" not in prop and "examples" not in prop


def test_openapi_marks_every_private_operation_as_secured(client: TestClient) -> None:
    """Solo health y login son públicos; el resto declara el esquema Bearer."""
    schema = client.get("/openapi.json").json()
    public = {
        ("get", "/health"),
        ("get", "/health/ready"),
        ("post", "/auth/token"),
        # Fase 2: lectura del catálogo para el lector anónimo (solo metadatos).
        ("get", "/datasets"),
        ("get", "/datasets/{slug}"),
        ("get", "/datasets/{slug}/rdf"),
        ("get", "/dataset/{slug}"),
        ("get", "/dataset/{slug}/{version}"),
        # Fase 3: lectura de vocabularios y ontologías y sus URIs persistentes.
        ("get", "/vocabularies"),
        ("get", "/ontologies/{slug}"),
        ("get", "/ontologies/{slug}/rdf"),
        ("get", "/schemes/{slug}"),
        ("get", "/schemes/{slug}/rdf"),
        ("get", "/schemes/{slug}/concepts/{concept}"),
        ("get", "/schemes/corp/{slug}"),
        ("get", "/schemes/corp/{slug}/rdf"),
        ("get", "/schemes/corp/{slug}/concepts/{concept}"),
        ("get", "/onto/{slug}"),
        ("get", "/onto/{slug}/{version}"),
        ("get", "/vocab/{slug}"),
        ("get", "/vocab/{slug}/{concept}"),
        ("get", "/vocab/corp/{slug}"),
        ("get", "/vocab/corp/{slug}/{concept}"),
        # Fase 4: informe FAIR y URI persistente de una distribución.
        ("get", "/datasets/{slug}/versions/{version}/fair/report"),
        ("get", "/dataset/{slug}/{version}/{dist}"),
        # Decisión 49: lectura de catálogos y sus URIs persistentes.
        ("get", "/catalogs"),
        ("get", "/catalogs/{slug}"),
        ("get", "/catalogo"),
        ("get", "/catalogo/{slug}"),
    }
    seen = set()
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            seen.add((method, path))
            if (method, path) in public:
                assert "security" not in operation, (method, path)
            else:
                assert operation.get("security") == [{"OAuth2PasswordBearer": []}], (method, path)
    assert public <= seen
    # Si aparece un endpoint nuevo, hay que decidir aquí si es público y probar sus roles.
    assert seen == public | {
        ("get", "/auth/me"),
        ("get", "/users"),
        ("post", "/users"),
        ("patch", "/users/{user_id}"),
        ("post", "/datasets"),
        ("post", "/ontologies"),
        ("post", "/schemes"),
        # Decisión 50: edición y baja de esquemas y ontologías (editor; admin hereda).
        ("patch", "/schemes/{slug}"),
        ("delete", "/schemes/{slug}"),
        ("patch", "/schemes/corp/{slug}"),
        ("delete", "/schemes/corp/{slug}"),
        ("patch", "/ontologies/{slug}"),
        ("delete", "/ontologies/{slug}"),
        # Decisión 49: CRUD de catálogos y datasets (editor; admin hereda).
        ("post", "/catalogs"),
        ("patch", "/catalogs/{slug}"),
        ("delete", "/catalogs/{slug}"),
        ("post", "/catalogs/{slug}/datasets"),
        ("patch", "/datasets/{slug}"),
        ("delete", "/datasets/{slug}"),
        # Fase 4. Con token opcional (públicos, pero con JWT cambia el límite o el acceso):
        # el fichero (RESTRICTED), el SPARQL y el listado de consultas guardadas.
        ("get", "/dataset/{slug}/{version}/{dist}/fichero"),
        ("get", "/sparql"),
        ("post", "/sparql"),
        ("get", "/sparql/queries"),
        # Con cuenta.
        ("put", "/datasets/{slug}/versions/{version}/distributions/{dist}/file"),
        ("post", "/datasets/{slug}/versions/{version}/distributions/{dist}/download-link"),
        ("post", "/datasets/{slug}/versions/{version}/fair"),
        ("post", "/sparql/queries"),
        ("put", "/sparql/queries/{query_id}"),
        ("delete", "/sparql/queries/{query_id}"),
    }


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_docs_pages_do_not_embed_secrets(client: TestClient, settings: Settings, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert settings.jwt_secret not in response.text
    assert "postgresql" not in response.text
    assert "password_hash" not in response.text
    assert not _EMAIL.search(response.text)
    assert "persistAuthorization" not in response.text  # no guarda el token en localStorage


def test_unknown_paths_and_errors_do_not_leak_internals(client: TestClient) -> None:
    for path in ("/.env", "/admin", "/users/../.env", "/openapi.yaml", "/metrics", "/debug"):
        response = client.get(path)
        assert response.status_code in (401, 404), path
        assert "Traceback" not in response.text
        assert "site-packages" not in response.text
    response = client.patch("/users/no-es-uuid", json={"role": "admin"})
    assert response.status_code == 401  # la autenticación va antes que la validación


def test_readiness_error_detail_does_not_leak_connection_data(
    client: TestClient, settings: Settings, fuseki_status: dict[str, Any]
) -> None:
    from app.schemas import ComponentStatus

    fuseki_status["value"] = ComponentStatus(status="error", detail="Fuseki no responde (X)")
    text = client.get("/health/ready").text
    assert settings.fuseki_url not in text
    assert settings.database_url not in text or settings.database_url == "sqlite://"
    assert settings.jwt_secret not in text


# --- CORS ----------------------------------------------------------------------------

DISALLOWED_ORIGINS = [
    "http://atacante.test",
    "https://localhost:5173",  # mismo host, otro esquema
    "http://localhost:5174",  # otro puerto
    "http://localhost:51730",  # el permitido como prefijo
    "http://localhost:5173.atacante.test",  # el permitido como prefijo de otro dominio
    "http://atacante.test/http://localhost:5173",
    "http://LOCALHOST:5173.atacante.test",
    "null",
]


@pytest.mark.parametrize("origin", DISALLOWED_ORIGINS)
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
def test_cors_preflight_from_disallowed_origin(
    client: TestClient, origin: str, method: str
) -> None:
    response = client.options(
        "/users",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("origin", DISALLOWED_ORIGINS)
def test_cors_simple_requests_from_disallowed_origin_get_no_cors_headers(
    client: TestClient, make_user: Callable[..., User], origin: str
) -> None:
    make_user("cors")
    responses = [
        client.get("/health", headers={"Origin": origin}),
        client.get("/auth/me", headers={"Origin": origin}),
        client.post(
            "/auth/token",
            data={"username": "cors", "password": DEFAULT_PASSWORD},
            headers={"Origin": origin},
        ),
    ]
    for response in responses:
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-credentials" not in response.headers


def test_cors_allowed_origin_is_echoed_exactly_and_without_credentials(
    client: TestClient,
) -> None:
    preflight = client.options(
        "/users",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "access-control-allow-credentials" not in preflight.headers
    methods_header = preflight.headers["access-control-allow-methods"]
    allowed_methods = {method.strip() for method in methods_header.split(",")}
    assert "*" not in allowed_methods
    assert "TRACE" not in allowed_methods

    simple = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})
    assert simple.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert simple.headers["access-control-allow-origin"] != "*"
    assert "access-control-allow-credentials" not in simple.headers


def test_cors_preflight_rejects_unlisted_request_headers(client: TestClient) -> None:
    response = client.options(
        "/users",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-cabecera-rara",
        },
    )
    assert response.status_code == 400


def test_cors_is_disabled_without_configured_origins(
    settings: Settings, session_factory: sessionmaker[Session]
) -> None:
    """Con ``CORS_ORIGINS`` vacío no se añade ninguna cabecera CORS (no hay comodín)."""
    from app.main import create_app

    app = create_app(settings.model_copy(update={"cors_origins": ""}))
    with TestClient(app) as bare:
        response = bare.get("/health", headers={"Origin": "http://atacante.test"})
        assert response.status_code == 200
        assert not [h for h in response.headers if h.startswith("access-control-")]
