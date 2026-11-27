"""Humo de autenticación y escritura.

Sin credenciales solo comprueba que NO se puede escribir sin token (con cuerpos vacíos o
inválidos, de modo que aunque el control fallase no se crearía nada). Con credenciales
comprueba login y rol. La única escritura real exige ``SMOKE_ALLOW_WRITE=1``.
"""

from __future__ import annotations

import json
import re
import secrets

import pytest
from smokelib import Config, request

# Operaciones de escritura que se prueban sin token. POST /auth/token y POST /sparql son
# públicas por diseño (login y consulta).
PUBLIC_POSTS = {"/auth/token", "/sparql"}


def _write_operations(cfg: Config) -> list[tuple[str, str]]:
    spec = json.loads(request(cfg, "GET", f"{cfg.api}/openapi.json").content)
    operations = []
    for path, item in spec["paths"].items():
        for method in item:
            if (
                method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
                and path not in PUBLIC_POSTS
            ):
                operations.append((method.upper(), path))
    return operations


def test_ninguna_escritura_ni_administracion_sin_token(cfg: Config) -> None:
    operations = _write_operations(cfg)
    assert len(operations) > 10, (
        f"pocas operaciones de escritura en el OpenAPI: {operations}"
    )
    failures = []
    for method, path in operations:
        concrete = re.sub(r"\{[^}]+\}", "smoke-inexistente", path)
        # Sin token, y con un token inválido, el resultado debe ser 401 o 403.
        for token in (None, "token.manipulado.smoke"):
            response = request(
                cfg, method, f"{cfg.api}{concrete}", token=token, json_body={}
            )
            if response.status not in {401, 403}:
                failures.append(
                    f"{method} {path} token={'sí' if token else 'no'}: {response.status}"
                )
    assert not failures, "escrituras no protegidas:\n" + "\n".join(failures)


@pytest.mark.parametrize("path", ["/auth/me", "/users"])
def test_lecturas_privadas_exigen_token(cfg: Config, path: str) -> None:
    assert request(cfg, "GET", f"{cfg.api}{path}").status == 401


def test_login_incorrecto_da_401(cfg: Config) -> None:
    response = request(
        cfg,
        "POST",
        f"{cfg.api}/auth/token",
        form={"username": "smoke-no-existe", "password": secrets.token_hex(8)},
    )
    assert response.status == 401, response.status


# --- Con credenciales -------------------------------------------------------------------


def test_login_y_rol_del_editor(cfg: Config, editor_token: str) -> None:
    response = request(cfg, "GET", f"{cfg.api}/auth/me", token=editor_token)
    assert response.status == 200, response.status
    assert response.json()["role"] in {"editor", "admin"}, response.json()  # type: ignore[index]


def test_el_editor_no_administra_usuarios(cfg: Config, editor_token: str) -> None:
    me = request(cfg, "GET", f"{cfg.api}/auth/me", token=editor_token).json()
    if me["role"] == "admin":  # type: ignore[index]
        pytest.skip("la cuenta es admin")
    assert request(cfg, "GET", f"{cfg.api}/users", token=editor_token).status == 403


def test_un_miembro_no_puede_escribir(cfg: Config, member_token: str) -> None:
    me = request(cfg, "GET", f"{cfg.api}/auth/me", token=member_token).json()
    assert me["role"] == "miembro", me  # type: ignore[index]
    # Cuerpo vacío: aunque el control fallase, la validación impide crear nada.
    for method, path in [
        ("POST", "/catalogs"),
        ("POST", "/datasets"),
        ("POST", "/ontologies"),
        ("DELETE", "/catalogs/smoke-inexistente"),
    ]:
        response = request(
            cfg, method, f"{cfg.api}{path}", token=member_token, json_body={}
        )
        assert response.status == 403, f"{method} {path}: {response.status}"
    assert request(cfg, "GET", f"{cfg.api}/users", token=member_token).status == 403


# --- Escritura opcional (SMOKE_ALLOW_WRITE=1) -------------------------------------------


def test_crear_y_dar_de_baja_un_catalogo_de_prueba(
    cfg: Config, editor_token: str
) -> None:
    if not cfg.allow_write:
        pytest.skip(
            "SMOKE_ALLOW_WRITE=1 para activarla (crea y borra un catálogo de prueba)"
        )
    slug = f"smoke-{secrets.token_hex(4)}"
    body = {
        "slug": slug,
        "title": "[PRUEBA DE HUMO] Catálogo temporal",
        "description": "Catálogo ficticio de la prueba de humo del despliegue. Se borra al terminar.",
        "publisher_name": "Prueba de humo",
    }
    created = False
    try:
        response = request(
            cfg, "POST", f"{cfg.api}/catalogs", token=editor_token, json_body=body
        )
        created = response.status in {200, 201}
        assert created, f"crear catálogo: {response.status} {response.text[:300]}"
        read = request(cfg, "GET", f"{cfg.api}/catalogs/{slug}")
        assert read.status == 200, read.status
        assert read.json()["slug"] == slug  # type: ignore[index]
    finally:
        # Se intenta borrar siempre, aunque la creación haya dado un error ambiguo.
        deleted = request(
            cfg, "DELETE", f"{cfg.api}/catalogs/{slug}", token=editor_token
        )
        if created or deleted.status != 404:
            assert deleted.status in {200, 204}, (
                f"LIMPIEZA FALLIDA: el catálogo {slug} sigue en el despliegue "
                f"({deleted.status}); bórralo a mano"
            )
    gone = request(cfg, "GET", f"{cfg.api}/catalogs/{slug}")
    assert gone.status in {404, 410}, (
        f"el catálogo sigue visible tras borrarlo: {gone.status}"
    )
