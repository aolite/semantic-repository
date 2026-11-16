"""Límite de frecuencia con ventana fija de un minuto, guardado en la base de datos.

Va en PostgreSQL (tabla ``rate_limit_counters``) para que valga igual con varios workers
de uvicorn o varias réplicas del backend: el contador se incrementa con un
``INSERT … ON CONFLICT DO UPDATE … RETURNING`` atómico. La ventana fija admite, en el peor
caso, el doble del límite en dos minutos consecutivos (al final de uno y al principio del
siguiente); para el SPARQL público del MVP basta.

Las filas de ventanas pasadas se borran de vez en cuando (``CLEANUP_EVERY``).
"""

import math
import time
from itertools import count

from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models import RateLimitCounter

WINDOW_SECONDS = 60
CLEANUP_EVERY = 200
_calls = count()


def hit(session: Session, key: str, limit: int, now: float | None = None) -> int | None:
    """Cuenta una petición. Devuelve ``None`` si cabe o los segundos de ``Retry-After``."""
    now = time.time() if now is None else now
    window = int(now // WINDOW_SECONDS)
    dialect = session.get_bind().dialect.name
    module = postgresql if dialect == "postgresql" else sqlite
    statement = module.insert(RateLimitCounter).values(key=key[:160], window=window, count=1)
    statement = statement.on_conflict_do_update(
        index_elements=["key", "window"],
        set_={"count": RateLimitCounter.count + 1},
    ).returning(RateLimitCounter.count)
    current = session.execute(statement).scalar_one()
    if next(_calls) % CLEANUP_EVERY == 0:
        session.execute(delete(RateLimitCounter).where(RateLimitCounter.window < window - 1))
    session.commit()
    if current > limit:
        return max(1, math.ceil((window + 1) * WINDOW_SECONDS - now))
    return None
