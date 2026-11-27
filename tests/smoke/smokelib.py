"""Utilidades de la prueba de humo del despliegue (solo biblioteca estándar).

No reutiliza el ``http()`` de ``tests/e2e``: aquel solo admite 127.0.0.1 y esta suite se
lanza contra URLs configurables. Ver ``tests/smoke/README.md``.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

TIMEOUT_SECONDS = float(os.environ.get("SMOKE_TIMEOUT", "10"))


WARNINGS: list[str] = []


def warn(message: str) -> None:
    """Aviso que no hace fallar la prueba (se resume al final de la ejecución)."""
    WARNINGS.append(message)


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Config:
    frontend: str
    api: str
    base_uri: str
    insecure_tls: bool
    allow_write: bool
    check_ports: bool
    http_port: int
    editor_user: str | None = field(repr=False)
    editor_password: str | None = field(repr=False)
    member_user: str | None = field(repr=False)
    member_password: str | None = field(repr=False)

    @property
    def api_host(self) -> str:
        return urllib.parse.urlsplit(self.api).hostname or ""

    @property
    def frontend_host(self) -> str:
        return urllib.parse.urlsplit(self.frontend).hostname or ""

    def https_urls(self) -> list[str]:
        return [
            u
            for u in dict.fromkeys([self.api, self.frontend])
            if u.startswith("https://")
        ]


def load_config() -> Config:
    env = os.environ.get
    return Config(
        frontend=env("SMOKE_FRONTEND_URL", "http://localhost:5173").rstrip("/"),
        api=env("SMOKE_API_URL", "http://localhost:18000").rstrip("/"),
        base_uri=env("SMOKE_BASE_URI", "https://semantic.example.org/itot/").rstrip("/")
        + "/",
        insecure_tls=_flag("SMOKE_INSECURE_TLS"),
        allow_write=env("SMOKE_ALLOW_WRITE") == "1",
        check_ports=env("SMOKE_CHECK_PORTS") == "1",
        http_port=int(env("SMOKE_HTTP_PORT", "80")),
        editor_user=env("SMOKE_EDITOR_USER") or None,
        editor_password=env("SMOKE_EDITOR_PASSWORD") or None,
        member_user=env("SMOKE_MEMBER_USER") or None,
        member_password=env("SMOKE_MEMBER_PASSWORD") or None,
    )


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self) -> object:
        return json.loads(self.content)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _ssl_context(insecure: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def request(
    cfg: Config,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    json_body: object | None = None,
    raw_body: bytes | None = None,
    token: str | None = None,
    follow: bool = False,
    timeout: float | None = None,
) -> Response:
    """Petición HTTP que devuelve también las 3xx (sin seguirlas), 4xx y 5xx."""
    hdrs = dict(headers or {})
    data = raw_body
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.setdefault("User-Agent", "semantic-repository-smoke/1")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.HTTPSHandler(context=_ssl_context(cfg.insecure_tls))
    ]
    if not follow:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout or TIMEOUT_SECONDS) as raw:
            return Response(
                raw.status, {k.lower(): v for k, v in raw.headers.items()}, raw.read()
            )
    except urllib.error.HTTPError as error:
        return Response(
            error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()
        )


def api_path(cfg: Config, uri: str) -> str:
    """URL de la API que atiende una URI persistente del catálogo.

    La URI debe colgar de ``SMOKE_BASE_URI``; se pide a la API con su ruta relativa al
    ``BASE_URI`` (``dataset/x``) colgada de ``SMOKE_API_URL``. Vale en local (``BASE_URI``
    ficticio y API en localhost) y en el piloto.
    """
    assert uri.startswith(cfg.base_uri), (
        f"La URI {uri} no cuelga de SMOKE_BASE_URI ({cfg.base_uri}): el BASE_URI del "
        "despliegue no coincide con el esperado"
    )
    return f"{cfg.api}/{uri[len(cfg.base_uri) :]}"


def port_is_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
