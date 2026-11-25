"""Bloqueo de las escrituras del catálogo (QA-49-01 y QA-49-03, decisión 49).

Las escrituras sueltas en el triplestore ya son atómicas (``app.bajas``: ``POST`` del Graph
Store Protocol y SPARQL Update), pero varias operaciones tienen que **comprobar y
escribir** sin que otra petición se cuele entre medias, y eso Fuseki no lo garantiza
entre dos peticiones HTTP:

- crear un catálogo o un dataset: «el slug no existe ni está dado de baja» + crearlo;
- dar de baja un catálogo: «no tiene datasets» + lápida (si no, un dataset movido a la
  vez quedaría colgado de un catálogo dado de baja);
- editar los metadatos de un catálogo o de una serie, y publicar una serie: se escribe el
  grafo entero (``PUT``) a partir de lo leído, y no puede pisar un cambio simultáneo;
- la fase de escritura de ``load-semantic`` (catálogos, series y ficheros).

``catalog_write_lock(session)`` serializa todas ellas. Es un bloqueo global y no por
recurso a propósito: las escrituras del catálogo son pocas (las hace un editor desde un
formulario) y tocan grafos compartidos (raíz, bajas y catálogo de origen y de destino), así
que un orden total es lo más simple y no hay riesgo de interbloqueo entre dos claves.

**Sin agotar el pool (QA-49-03).** Mientras se espera el bloqueo no se retiene ninguna
conexión del pool de la aplicación:

1. Antes de esperar, se cierra la transacción de la sesión (``commit``; no debe haber
   cambios pendientes, y con ``expire_on_commit=False`` los objetos ya leídos, como el
   usuario, siguen valiendo). La conexión vuelve al pool y la sesión pide otra cuando la
   necesite (la auditoría, al final).
2. Primero se espera el ``RLock`` del proceso, que no usa ninguna conexión: en cada proceso
   solo hay un hilo a la vez en el paso siguiente.
3. Con PostgreSQL, el que tiene el ``RLock`` toma un **advisory lock** de sesión
   (``pg_advisory_lock``), que vale entre procesos y réplicas (varios workers de la API y la
   CLI a la vez), en una conexión **fuera del pool** de la aplicación (``NullPool``): como
   mucho una por proceso, abierta solo mientras se espera o se tiene el bloqueo.

Así, con N escrituras simultáneas, las que esperan no tienen conexión, la que escribe usa
una de la sesión solo cuando la necesita, y los endpoints de lectura (``GET /auth/me``…)
siguen teniendo el pool libre.

**Espera acotada.** Esperar el ``RLock`` y el advisory lock (``lock_timeout`` de PostgreSQL)
tiene como máximo ``CATALOG_LOCK_TIMEOUT_SECONDS`` en total. Si vence, se lanza
``CatalogLockTimeoutError``, que la API convierte en 503 y la CLI en un error claro.

Es reentrante en el mismo hilo: ``create_series`` publica la serie dentro de su propio
bloqueo.
"""

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import ConfigurationError, get_settings

# Clave del advisory lock (bigint). Fija y propia de este backend.
LOCK_KEY = 4_904_900_001
DEFAULT_TIMEOUT_SECONDS = 30.0

logger = logging.getLogger(__name__)
_process_lock = threading.RLock()
_local = threading.local()


class CatalogLockTimeoutError(RuntimeError):
    """No se ha conseguido el bloqueo de escritura a tiempo (``CATALOG_LOCK_TIMEOUT_SECONDS``)."""

    def __init__(self, timeout: float) -> None:
        super().__init__(
            "Hay otra escritura del catálogo en curso y no ha terminado a tiempo "
            f"({timeout:g} s, CATALOG_LOCK_TIMEOUT_SECONDS): vuelve a intentarlo"
        )


def _timeout() -> float:
    try:
        return get_settings().catalog_lock_timeout_seconds
    except ConfigurationError:  # pragma: no cover - sin configuración (scripts sueltos)
        return DEFAULT_TIMEOUT_SECONDS


def _release_session(session: Session) -> None:
    """Cierra la transacción de la sesión para que su conexión vuelva al pool."""
    if session.new or session.dirty or session.deleted:
        raise RuntimeError(
            "catalog_write_lock: la sesión tiene cambios sin confirmar; confírmalos antes"
        )
    if session.in_transaction():
        session.commit()


@lru_cache(maxsize=4)
def _lock_engine(url: str) -> Engine:
    """Motor sin pool para el advisory lock: no compite con el pool de la aplicación."""
    return create_engine(url, poolclass=NullPool)


def _acquire_advisory(engine: Engine, remaining: float, timeout: float) -> Connection:
    url = engine.url.render_as_string(hide_password=False)
    connection = _lock_engine(url).connect()
    try:
        milliseconds = max(int(remaining * 1000), 1)
        connection.execute(
            text("SELECT set_config('lock_timeout', :value, false)"),
            {"value": f"{milliseconds}ms"},
        )
        try:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
        except DBAPIError as exc:  # lock_timeout vencido
            raise CatalogLockTimeoutError(timeout) from exc
        connection.commit()
    except BaseException:
        connection.close()  # sin pool: cierra de verdad la conexión
        raise
    return connection


def _release_advisory(connection: Connection) -> None:
    try:
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        connection.commit()
    except Exception:  # noqa: BLE001 - al cerrar la conexión se libera igualmente
        logger.warning("No se ha podido liberar el advisory lock; se cierra la conexión")
    finally:
        connection.close()


@contextmanager
def catalog_write_lock(session: Session, timeout: float | None = None) -> Iterator[None]:
    if getattr(_local, "depth", 0):
        _local.depth += 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    limit = _timeout() if timeout is None else timeout
    _release_session(session)
    deadline = time.monotonic() + limit
    if not _process_lock.acquire(timeout=limit):
        raise CatalogLockTimeoutError(limit)
    connection: Connection | None = None
    try:
        bind = session.get_bind()
        engine = getattr(bind, "engine", bind)
        if engine.dialect.name == "postgresql":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CatalogLockTimeoutError(limit)
            connection = _acquire_advisory(engine, remaining, limit)
        _local.depth = 1
        try:
            yield
        finally:
            _local.depth = 0
    finally:
        if connection is not None:
            _release_advisory(connection)
        _process_lock.release()
