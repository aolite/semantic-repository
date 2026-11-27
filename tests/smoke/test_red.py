"""Humo de red: HTTPS (certificado, redirección, cabeceras) y servicios internos cerrados."""

from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.parse

import pytest
from smokelib import TIMEOUT_SECONDS, Config, port_is_open, request, warn

# Fuseki y PostgreSQL, en sus puertos habituales y en los que publica el Compose local.
INTERNAL_PORTS = [3030, 13030, 5432, 15432]
SECURITY_HEADERS = {
    "strict-transport-security": "HSTS",
    "x-content-type-options": "X-Content-Type-Options",
    "referrer-policy": "Referrer-Policy",
}


def _https_urls(cfg: Config) -> list[str]:
    urls = cfg.https_urls()
    if not urls:
        pytest.skip("el despliegue no es HTTPS")
    return urls


def test_el_certificado_es_valido(cfg: Config) -> None:
    if cfg.insecure_tls:
        pytest.skip("SMOKE_INSECURE_TLS=1: no se valida el certificado")
    for url in _https_urls(cfg):
        parts = urllib.parse.urlsplit(url)
        host, port = parts.hostname or "", parts.port or 443
        context = ssl.create_default_context()
        try:
            with (
                socket.create_connection((host, port), timeout=TIMEOUT_SECONDS) as raw,
                context.wrap_socket(raw, server_hostname=host) as tls,
            ):
                cert = tls.getpeercert()
        except ssl.SSLError as error:
            pytest.fail(f"{url}: certificado no válido: {error}")
        remaining = (ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()) / 86400  # type: ignore[index]
        assert remaining > 0, f"{url}: certificado caducado"
        if remaining < 14:
            warn(f"{url}: el certificado caduca en {remaining:.0f} días")


def test_http_redirige_a_https(cfg: Config) -> None:
    for url in _https_urls(cfg):
        host = urllib.parse.urlsplit(url).hostname or ""
        connection = http.client.HTTPConnection(
            host, cfg.http_port, timeout=TIMEOUT_SECONDS
        )
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
        except OSError as error:
            pytest.fail(
                f"http://{host}:{cfg.http_port} no responde ({error}); ¿SMOKE_HTTP_PORT?"
            )
        finally:
            connection.close()
        location = response.getheader("Location", "")
        assert response.status in {301, 302, 307, 308}, (
            f"{host}: HTTP no redirige ({response.status})"
        )
        assert location.startswith("https://"), f"{host}: redirige a {location!r}"


def test_cabeceras_de_seguridad(cfg: Config) -> None:
    # Solo avisos: infra las configura aparte.
    for url in _https_urls(cfg):
        response = request(
            cfg, "GET", f"{url}/" if url == cfg.frontend else f"{url}/health"
        )
        for header, name in SECURITY_HEADERS.items():
            if header not in response.headers:
                warn(f"{url}: falta la cabecera {name}")
        if (
            "x-frame-options" not in response.headers
            and "content-security-policy" not in response.headers
        ):
            warn(
                f"{url}: falta X-Frame-Options o Content-Security-Policy (frame-ancestors)"
            )


def test_fuseki_y_postgres_no_son_accesibles_desde_fuera(cfg: Config) -> None:
    if not cfg.check_ports:
        pytest.skip(
            "SMOKE_CHECK_PORTS=1 para activarla (en local los puertos sí están publicados)"
        )
    hosts = dict.fromkeys([cfg.api_host, cfg.frontend_host])
    open_ports = [
        f"{h}:{p}" for h in hosts for p in INTERNAL_PORTS if port_is_open(h, p)
    ]
    assert not open_ports, f"puertos internos accesibles desde fuera: {open_ports}"
