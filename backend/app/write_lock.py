"""Bloqueo de las escrituras del catálogo (QA-49-01, decisión 49).

Las escrituras sueltas en el triplestore ya son atómicas (``app.bajas``: ``POST`` del Graph
Store Protocol y SPARQL Update), pero varias operaciones tienen que **comprobar y
escribir** sin que otra petición se cuele entre medias, y eso Fuseki no lo garantiza
entre dos peticiones HTTP:

- crear un catálogo o un dataset: «el slug no existe ni está dado de baja» + crearlo;
- dar de baja un catálogo: «no tiene datasets» + lápida (si no, un dataset movido a la
  vez quedaría colgado de un catálogo dado de baja);
- editar los metadatos de un catálogo o de una serie, y publicar una serie: se escribe el
  grafo entero (``PUT``) a partir de lo leído, y no puede pisar un cambio simultáneo;
- ``load-semantic``, que fusiona los catálogos con lo publicado.

``catalog_write_lock(session)`` serializa todas ellas:

- Con PostgreSQL, un **advisory lock** de sesión (``pg_advisory_lock``) en una conexión
  propia, que vale entre procesos y réplicas del backend (la API con varios workers y la
  CLI a la vez). Va en una conexión aparte, y no en la de la sesión de SQLAlchemy, porque
  las operaciones hacen ``commit`` (auditoría) y la sesión devuelve su conexión al pool.
- Además, siempre, un ``RLock`` del proceso (con SQLite, el de las pruebas, es el único).
- Es reentrante en el mismo hilo: ``create_series`` publica la serie y ``load-semantic``
  publica varias dentro de su propio bloqueo.

Es un bloqueo global y no por recurso a propósito: las escrituras del catálogo son pocas
(las hace un editor desde un formulario) y tocan grafos compartidos (el raíz, el de
bajas y el del catálogo de origen y de destino), así que un orden total es lo más simple
y no hay riesgo de interbloqueo entre dos claves.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

# Clave del advisory lock (bigint). Fija y propia de este backend.
LOCK_KEY = 4_904_900_001

_process_lock = threading.RLock()
_local = threading.local()


@contextmanager
def catalog_write_lock(session: Session) -> Iterator[None]:
    if getattr(_local, "depth", 0):
        _local.depth += 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    with _process_lock:
        bind = session.get_bind()
        engine = getattr(bind, "engine", bind)
        connection = None
        if engine.dialect.name == "postgresql":
            connection = engine.connect()
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
            connection.commit()
        _local.depth = 1
        try:
            yield
        finally:
            _local.depth = 0
            if connection is not None:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                    connection.commit()
                except Exception:  # noqa: BLE001 - sin desbloquear, la conexión no vuelve al pool
                    connection.invalidate()
                finally:
                    connection.close()
