"""Validación SHACL en un proceso aparte, con tiempo y memoria limitados (QA-G3-10).

pyshacl no se puede interrumpir desde otro hilo: un grafo grande o unas formas costosas
bloquearían un hilo del servidor durante minutos. Por eso cada validación se ejecuta en un
proceso hijo:

- **Tiempo:** si no termina en ``SHACL_TIMEOUT_SECONDS``, el proceso se mata (``SIGKILL``)
  y la ingesta responde 422 (``kind=limit``). No queda ningún hilo ni proceso colgado.
- **Memoria:** el hijo fija ``RLIMIT_AS`` a ``SHACL_MEMORY_MB`` (en Linux; en macOS el
  límite no se aplica). Si se agota, la ingesta responde 422 (``kind=limit``).

Los procesos salen de un *forkserver* que ya tiene importados rdflib, pyshacl y el módulo
principal, así que crear uno cuesta milisegundos. Donde no hay forkserver se usa *spawn*.

El grafo de datos, las formas y el grafo de soporte viajan en N-Triples y el informe vuelve
igual: no se comparte memoria con el servidor.
"""

import logging
import multiprocessing as mp
from dataclasses import dataclass
from multiprocessing.connection import Connection
from threading import Lock

logger = logging.getLogger(__name__)

_CONTEXT: mp.context.BaseContext | None = None
_CONTEXT_LOCK = Lock()


class ShaclLimitError(RuntimeError):
    """La validación superó el tiempo o la memoria permitidos."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason  # "timeout" | "memory"


class ShaclWorkerError(RuntimeError):
    """El proceso de validación falló por otro motivo (el detalle va al log)."""


@dataclass
class ShaclOutcome:
    conforms: bool
    results_nt: bytes
    report: str


def _context() -> mp.context.BaseContext:
    global _CONTEXT
    with _CONTEXT_LOCK:
        if _CONTEXT is None:
            if "forkserver" in mp.get_all_start_methods():
                context = mp.get_context("forkserver")
                # «__main__»: el forkserver importa una sola vez el módulo principal (uvicorn,
                # la CLI o pytest). Sin él, cada hijo lo vuelve a importar al arrancar, y eso
                # costaba ~0,25 s por validación.
                context.set_forkserver_preload(
                    ["__main__", "app.shacl_worker", "pyshacl", "rdflib"]
                )
            else:  # pragma: no cover - plataformas sin forkserver
                context = mp.get_context("spawn")
            _CONTEXT = context
        return _CONTEXT


def _limit_memory(memory_mb: int) -> None:
    try:
        import resource

        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except ImportError, ValueError, OSError:  # pragma: no cover - según la plataforma
        pass


def _worker(
    conn: Connection,
    data_nt: bytes,
    shapes_nt: bytes,
    support_nt: bytes | None,
    memory_mb: int,
) -> None:  # pragma: no cover - se ejecuta en el proceso hijo
    _limit_memory(memory_mb)
    try:
        from pyshacl import validate
        from rdflib import Graph

        data = Graph().parse(data=data_nt, format="nt")
        shapes = Graph().parse(data=shapes_nt, format="nt")
        support = Graph().parse(data=support_nt, format="nt") if support_nt else None
        conforms, results, text = validate(
            data,
            shacl_graph=shapes,
            ont_graph=support,
            inference="none",
            abort_on_first=False,
            allow_warnings=True,
            meta_shacl=False,
            advanced=False,
        )
        conn.send(("ok", bool(conforms), results.serialize(format="nt", encoding="utf-8"), text))
    except MemoryError:
        conn.send(("memory",))
    except BaseException as exc:  # noqa: BLE001 - cualquier fallo vuelve al padre
        conn.send(("error", f"{type(exc).__name__}: {str(exc)[:500]}"))
    finally:
        conn.close()


def validate(
    data_nt: bytes,
    shapes_nt: bytes,
    support_nt: bytes | None,
    *,
    timeout_seconds: float,
    memory_mb: int,
) -> ShaclOutcome:
    context = _context()
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(child, data_nt, shapes_nt, support_nt, memory_mb),
        daemon=True,
    )
    process.start()
    child.close()
    try:
        if not parent.poll(timeout_seconds):
            raise ShaclLimitError("timeout")
        try:
            message = parent.recv()
        except EOFError as exc:
            # El hijo murió sin responder: casi siempre, por el límite de memoria.
            raise ShaclLimitError("memory") from exc
    finally:
        if process.is_alive():
            process.kill()
        process.join(timeout=5)
        parent.close()
    kind = message[0]
    if kind == "ok":
        return ShaclOutcome(conforms=message[1], results_nt=message[2], report=message[3])
    if kind == "memory":
        raise ShaclLimitError("memory")
    logger.error("La validación SHACL falló en el proceso hijo: %s", message[1])
    raise ShaclWorkerError("la validación SHACL falló")
