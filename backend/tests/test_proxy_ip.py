"""IP del cliente detrás del proxy inverso (fase 5).

El backend usa ``request.client.host`` en el bloqueo de login y en el límite de SPARQL
anónimo. Quien decide esa IP es el ``ProxyHeadersMiddleware`` de uvicorn, con los proxies de
confianza de ``FORWARDED_ALLOW_IPS``. Estas pruebas montan la aplicación detrás de ese mismo
middleware, configurado como lo hace uvicorn al arrancar (``uvicorn.Config`` lee la variable
del entorno), y fijan la IP de la conexión con el parámetro ``client`` de ``TestClient``.
"""

from collections.abc import Callable

import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings
from app.models import LoginAttempt, User
from tests.conftest import DEFAULT_PASSWORD

PROXY_IP = "172.20.0.2"  # el proxy (Caddy) en la red de Docker
OTHER_CONTAINER_IP = "172.21.0.7"  # otro contenedor que llega al backend sin pasar por él
CLIENT_A = "203.0.113.10"
CLIENT_B = "203.0.113.20"
WRONG = "mala-contrasena-x"


@pytest.fixture
def behind_proxy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str, str | None], TestClient]:
    """Cliente HTTP que conecta desde ``ip`` con ``FORWARDED_ALLOW_IPS=allow`` (o sin ella)."""

    def _make(ip: str, allow: str | None) -> TestClient:
        if allow is None:
            monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
        else:
            monkeypatch.setenv("FORWARDED_ALLOW_IPS", allow)
        trusted = uvicorn.Config(client.app).forwarded_allow_ips
        app = ProxyHeadersMiddleware(client.app, trusted_hosts=trusted)
        return TestClient(app, client=(ip, 40000))

    return _make


def _login(http: TestClient, password: str, forwarded_for: str | None = None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return http.post("/auth/token", data={"username": "ana", "password": password}, headers=headers)


def _sparql(http: TestClient, forwarded_for: str | None = None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return http.get("/sparql", params={"query": "ASK {}"}, headers=headers)


def _locked_ips(db: Session) -> set[str]:
    db.expire_all()
    return {row.ip for row in db.scalars(select(LoginAttempt)) if row.locked_until is not None}


# --- Proxy de confianza ----------------------------------------------------------------------


def test_login_lockout_counts_each_forwarded_ip_separately(
    behind_proxy, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    make_user("ana")
    http = behind_proxy(PROXY_IP, PROXY_IP)
    for _ in range(settings.login_max_failures):
        assert _login(http, WRONG, CLIENT_A).status_code == 401
    assert _login(http, DEFAULT_PASSWORD, CLIENT_A).status_code == 429
    # Otro cliente detrás del mismo proxy no hereda el bloqueo.
    assert _login(http, DEFAULT_PASSWORD, CLIENT_B).status_code == 200
    assert _locked_ips(db) == {CLIENT_A}


def test_sparql_rate_limit_counts_each_forwarded_ip_separately(
    behind_proxy, settings: Settings
) -> None:
    settings.sparql_rate_anon_per_min = 2
    http = behind_proxy(PROXY_IP, PROXY_IP)
    for _ in range(2):
        assert _sparql(http, CLIENT_A).status_code == 200
    assert _sparql(http, CLIENT_A).status_code == 429
    assert _sparql(http, CLIENT_B).status_code == 200


def test_trusted_proxy_by_network_takes_last_untrusted_hop(
    behind_proxy, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    """Con la red del proxy (y no ``*``), un ``X-Forwarded-For`` que el cliente añada delante
    no sirve: uvicorn recorre la cabecera desde el final y se queda con el primer salto que no
    es de confianza, el que puso el proxy."""
    make_user("ana")
    http = behind_proxy(PROXY_IP, "172.20.0.0/16")
    for i in range(settings.login_max_failures):
        assert _login(http, WRONG, f"198.51.100.{i}, {CLIENT_A}").status_code == 401
    assert _locked_ips(db) == {CLIENT_A}


# --- Sin proxy de confianza --------------------------------------------------------------------


def test_forged_forwarded_for_does_not_change_login_ip(
    behind_proxy, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    make_user("ana")
    http = behind_proxy(OTHER_CONTAINER_IP, None)  # por defecto, solo 127.0.0.1 y ::1
    for i in range(settings.login_max_failures):
        assert _login(http, WRONG, f"198.51.100.{i}").status_code == 401
    assert _login(http, DEFAULT_PASSWORD, CLIENT_B).status_code == 429
    assert _locked_ips(db) == {OTHER_CONTAINER_IP}


def test_forged_forwarded_for_does_not_change_sparql_ip(behind_proxy, settings: Settings) -> None:
    settings.sparql_rate_anon_per_min = 2
    # Confía en el proxy, pero la conexión llega desde otro contenedor.
    http = behind_proxy(OTHER_CONTAINER_IP, PROXY_IP)
    assert _sparql(http, CLIENT_A).status_code == 200
    assert _sparql(http, CLIENT_B).status_code == 200
    assert _sparql(http, "198.51.100.1").status_code == 429


def test_wildcard_trusts_any_connection(
    behind_proxy, make_user: Callable[..., User], settings: Settings, db: Session
) -> None:
    """Con ``FORWARDED_ALLOW_IPS=*`` cualquier conexión es de confianza y cuenta el primer
    valor de la cabecera: un contenedor que llegue al backend sin pasar por el proxy elige
    la IP. Por eso en el despliegue se restringe a la IP del proxy (``backend/README.md``)."""
    make_user("ana")
    http = behind_proxy(OTHER_CONTAINER_IP, "*")
    assert _login(http, WRONG, f"{CLIENT_A}, {CLIENT_B}").status_code == 401
    db.expire_all()
    assert {row.ip for row in db.scalars(select(LoginAttempt))} == {CLIENT_A}
