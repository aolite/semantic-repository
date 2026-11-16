"""Evaluación FAIR de las versiones de dataset con F-UJI (decisión 45 y sección 5.5).

Flujo:

1. Al publicar una versión **nueva** (API o ``load-semantic``) se crea una fila
   ``pending`` en ``fair_evaluations`` (``enqueue``). La publicación no espera. Una versión
   que ya tiene alguna evaluación no se vuelve a encolar sola; un editor puede pedir otra
   (``request_reevaluation``).
2. Un trabajador en segundo plano (``FairWorker``, un hilo que arranca con la API) recoge
   las pendientes: cada fila se reclama con un ``UPDATE … WHERE status='pending'``
   atómico, así que con varios procesos del backend nadie evalúa dos veces lo mismo. Se
   despierta al publicar (``notify``) y, además, cada ``FAIR_WORKER_POLL_SECONDS`` (así
   recoge también lo que encola ``load-semantic``, que es otro proceso).
3. Se llama a ``POST {FUJI_URL}/evaluate`` (API de F-UJI, ``fuji_server/yaml/openapi.yaml``)
   con la URL del RDF de la versión bajo ``FAIR_TARGET_BASE_URL`` (``evaluation_target``:
   la URI persistente redirige con 303 al frontend, que F-UJI no alcanza), y el endpoint
   SPARQL equivalente como ``metadata_service_endpoint`` (``metadata_service_type=sparql``).
   La URL evaluada queda en ``fair_evaluations.evaluated_url``. ``use_datacite`` y
   ``use_github`` van a ``false`` para que F-UJI haga las menos llamadas externas posibles.
   El informe se guarda tal cual; al servirlo, ``public_report`` cambia
   ``FAIR_TARGET_BASE_URL`` por ``BASE_URI``.
4. Las puntuaciones salen **solo** de la respuesta de F-UJI: ``summary.score_percent`` por
   categoría (``F``, ``A``, ``I``, ``R``) y total (``FAIR``), tal cual (F-UJI ya las
   redondea a dos decimales), y el nivel de madurez de ``summary.maturity.FAIR``. Ese
   formato es el de ``FAIRCheck.get_assessment_summary`` (``fuji_server/controllers/
   fair_check.py``). Si falta algo o no es un número entre 0 y 100, la evaluación queda
   ``failed`` («respuesta no válida»): no se inventa ni se recalcula nada.
5. Cualquier error (F-UJI caído, timeout, respuesta no válida, sin credenciales) deja la
   fila ``failed`` con un mensaje fijo y saneado, sin trazas ni rutas. La ficha nunca se
   rompe por esto. Una fila ``running`` huérfana (el backend se reinició a mitad) se marca
   ``failed`` pasado ``FUJI_TIMEOUT_SECONDS`` más un margen.
"""

import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app import audit
from app.config import Settings
from app.models import AuditAction, FairEvaluation, User
from app.uris import Uris, is_slug, is_version

logger = logging.getLogger(__name__)

FairStatus = Literal["pending", "running", "done", "failed"]
PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"

CONNECT_TIMEOUT_SECONDS = 5.0
# Métricas de F-UJI (las de su server.ini por defecto; probadas con la imagen 4.0.1).
FUJI_METRIC_VERSION = "metrics_v0.5"
STALE_MARGIN_SECONDS = 120
MAX_EVALUATOR_LENGTH = 255

# Mensajes de error fijos: nunca incluyen trazas, rutas ni la respuesta de F-UJI.
ERROR_UNREACHABLE = "F-UJI no responde"
ERROR_TIMEOUT = "F-UJI superó el tiempo máximo de evaluación (FUJI_TIMEOUT_SECONDS)"
ERROR_INVALID = "La respuesta de F-UJI no es válida"
ERROR_NO_CREDENTIALS = "Faltan las credenciales de F-UJI (FUJI_USERNAME y FUJI_PASSWORD)"
ERROR_AUTH = "F-UJI rechazó las credenciales (FUJI_USERNAME y FUJI_PASSWORD)"
ERROR_INTERRUPTED = "La evaluación se interrumpió (el backend se reinició durante la evaluación)"
ERROR_UNEXPECTED = "Error inesperado durante la evaluación"


class FujiError(Exception):
    """Fallo de la evaluación con un mensaje ya saneado."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class FujiScores:
    total: float
    findable: float | None
    accessible: float | None
    interoperable: float | None
    reusable: float | None
    maturity: str | None
    evaluator: str


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if math.isnan(number) or not 0 <= number <= 100:
        return None
    return number


def parse_report(report: Any) -> FujiScores:
    """Puntuaciones del resumen de F-UJI. ``FujiError`` si el formato no es el esperado."""
    if not isinstance(report, dict):
        raise FujiError(ERROR_INVALID)
    summary = report.get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("score_percent"), dict):
        raise FujiError(ERROR_INVALID)
    percent = summary["score_percent"]
    total = _number(percent.get("FAIR"))
    if total is None:
        raise FujiError(ERROR_INVALID)
    categories: dict[str, float | None] = {}
    for key in ("F", "A", "I", "R"):
        if key in percent and _number(percent[key]) is None:
            raise FujiError(ERROR_INVALID)
        # Una categoría sin métricas no sale en el resumen de F-UJI: queda en null.
        categories[key] = _number(percent.get(key))
    maturity_map = summary.get("maturity")
    maturity_value = maturity_map.get("FAIR") if isinstance(maturity_map, dict) else None
    maturity = (
        str(maturity_value)
        if isinstance(maturity_value, int | float | str) and not isinstance(maturity_value, bool)
        else None
    )
    version = report.get("software_version")
    evaluator = f"F-UJI {version}" if isinstance(version, str) and version else "F-UJI"
    metric_version = report.get("metric_version")
    if isinstance(metric_version, str) and metric_version:
        evaluator = f"{evaluator} ({metric_version})"
    return FujiScores(
        total=total,
        findable=categories["F"],
        accessible=categories["A"],
        interoperable=categories["I"],
        reusable=categories["R"],
        maturity=maturity[:64] if maturity else None,
        evaluator=evaluator[:MAX_EVALUATOR_LENGTH],
    )


def target_url(settings: Settings, version_uri: str) -> str:
    """URI de la versión con ``BASE_URI`` sustituido por ``FAIR_TARGET_BASE_URL``."""
    if version_uri.startswith(settings.base_uri):
        return settings.fair_base_url + version_uri[len(settings.base_uri) :]
    return version_uri


def evaluation_target(settings: Settings, version_uri: str) -> str:
    """URL que se pasa a F-UJI como ``object_identifier`` (QA-G4-01).

    No es la URI persistente: F-UJI la pide con ``Accept: text/html, */*``, el backend
    responde 303 a la ficha del frontend (decisión 31) y F-UJI sigue la redirección. El
    frontend no está en la red de F-UJI (y aunque lo estuviera, es una aplicación de una
    sola página sin metadatos en el HTML), así que F-UJI no encuentra la página de destino
    y no recoge ningún metadato. Por eso se le da la representación RDF de la versión, que
    responde Turtle con cualquier ``Accept`` (``format=turtle``), construida desde
    ``FAIR_TARGET_BASE_URL``. El RDF identifica la versión con su URI persistente.
    """
    uris = Uris(settings.base_uri)
    if version_uri.startswith(uris.dataset_ns):
        slug, _, version = version_uri[len(uris.dataset_ns) :].partition("/")
        if is_slug(slug) and is_version(version):
            return f"{settings.fair_base_url}datasets/{slug}/rdf?version={version}&format=turtle"
    return target_url(settings, version_uri)


def public_report(
    settings: Settings,
    report: Any,
    *,
    evaluated_url: str | None = None,
    version_uri: str | None = None,
) -> Any:
    """Informe de F-UJI sin las URLs internas, para servirlo en la API.

    F-UJI repite la URL evaluada (y la del endpoint SPARQL) en la petición, en los
    resultados y en sus mensajes. Con ``FAIR_TARGET_BASE_URL`` apuntando a un host interno
    (``http://backend:8000/``), el informe público lo revelaría. Se sustituye:

    1. la URL evaluada (el RDF de la versión, ``evaluation_target``) por la URI persistente
       de la versión, que es lo que identifica al recurso evaluado;
    2. cualquier otra aparición de ``FAIR_TARGET_BASE_URL`` por ``BASE_URI``.

    El informe guardado en ``fair_evaluations.report`` no cambia.
    """
    internal = settings.fair_base_url
    public = settings.base_uri
    replacements: list[tuple[str, str]] = []
    if evaluated_url and version_uri and evaluated_url != version_uri:
        replacements.append((evaluated_url, version_uri))
    if internal != public:
        replacements += [(internal, public), (internal.rstrip("/"), public.rstrip("/"))]
    if not replacements:
        return report

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            for old, new in replacements:
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {clean(key): clean(item) for key, item in value.items()}
        return value

    return clean(report)


class FujiClient:
    """Cliente de la API de F-UJI (``POST /evaluate`` con autenticación Basic)."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def evaluate(self, identifier: str, sparql_endpoint: str | None) -> dict[str, Any]:
        credentials = self._settings.fuji_credentials
        if credentials is None:
            raise FujiError(ERROR_NO_CREDENTIALS)
        body: dict[str, Any] = {
            "object_identifier": identifier,
            "test_debug": False,
            "use_datacite": False,
            "use_github": False,
            "metric_version": FUJI_METRIC_VERSION,
        }
        if sparql_endpoint:
            body["metadata_service_endpoint"] = sparql_endpoint
            body["metadata_service_type"] = "sparql"
        timeout = httpx.Timeout(
            self._settings.fuji_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS
        )
        try:
            with httpx.Client(
                timeout=timeout, transport=self._transport, auth=httpx.BasicAuth(*credentials)
            ) as client:
                response = client.post(
                    f"{self._settings.fuji_url}/evaluate",
                    json=body,
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise FujiError(ERROR_TIMEOUT) from exc
        except httpx.HTTPError as exc:
            raise FujiError(ERROR_UNREACHABLE) from exc
        if response.status_code in (401, 403):
            raise FujiError(ERROR_AUTH)
        if response.status_code != 200:
            raise FujiError(f"F-UJI respondió {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise FujiError(ERROR_INVALID) from exc
        if not isinstance(data, dict):
            raise FujiError(ERROR_INVALID)
        return data


# --- Cola -------------------------------------------------------------------------------


def enqueue(
    session: Session,
    version_uris: list[str],
    *,
    requested_by: User | None = None,
    commit: bool = True,
) -> list[FairEvaluation]:
    """Encola las versiones que aún no tienen ninguna evaluación."""
    if not version_uris:
        return []
    known = set(
        session.scalars(
            select(FairEvaluation.version_uri).where(FairEvaluation.version_uri.in_(version_uris))
        )
    )
    created = []
    for uri in version_uris:
        if uri in known:
            continue
        row = FairEvaluation(
            version_uri=uri,
            status=PENDING,
            requested_by=requested_by.id if requested_by else None,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        created.append(row)
    if commit:
        session.commit()
    return created


def latest(session: Session, version_uri: str) -> FairEvaluation | None:
    return session.scalars(
        select(FairEvaluation)
        .where(FairEvaluation.version_uri == version_uri)
        .order_by(FairEvaluation.created_at.desc(), FairEvaluation.id.desc())
        .limit(1)
    ).first()


def latest_done(session: Session, version_uri: str) -> FairEvaluation | None:
    return session.scalars(
        select(FairEvaluation)
        .where(FairEvaluation.version_uri == version_uri, FairEvaluation.status == DONE)
        .order_by(FairEvaluation.finished_at.desc(), FairEvaluation.created_at.desc())
        .limit(1)
    ).first()


def latest_done_totals(session: Session, version_uris: list[str]) -> dict[str, float]:
    """``total`` de la última evaluación ``done`` de cada versión (tarjetas del catálogo)."""
    if not version_uris:
        return {}
    rows = session.execute(
        select(FairEvaluation.version_uri, FairEvaluation.score_total, FairEvaluation.finished_at)
        .where(FairEvaluation.version_uri.in_(version_uris), FairEvaluation.status == DONE)
        .order_by(FairEvaluation.finished_at.asc())
    )
    totals: dict[str, float] = {}
    for uri, total, _finished in rows:
        if total is not None:
            totals[uri] = total  # la más reciente queda la última
    return totals


def request_reevaluation(session: Session, version_uri: str, user: User) -> FairEvaluation:
    """Nueva evaluación pedida por un editor. Si ya hay una en curso, la devuelve."""
    current = latest(session, version_uri)
    if current is not None and current.status in (PENDING, RUNNING):
        return current
    row = FairEvaluation(
        version_uri=version_uri,
        status=PENDING,
        requested_by=user.id,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()
    notify()
    return row


# --- Ejecución ------------------------------------------------------------------------


def _aware(moment: datetime | None) -> datetime | None:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def fail_stale(session: Session, settings: Settings, now: datetime | None = None) -> int:
    """Marca ``failed`` las evaluaciones ``running`` que llevan demasiado tiempo."""
    now = now or datetime.now(UTC)
    limit = now - timedelta(seconds=settings.fuji_timeout_seconds + STALE_MARGIN_SECONDS)
    stale = [
        row
        for row in session.scalars(select(FairEvaluation).where(FairEvaluation.status == RUNNING))
        if (_aware(row.started_at) or now) < limit
    ]
    for row in stale:
        row.status = FAILED
        row.error = ERROR_INTERRUPTED
        row.finished_at = now
    if stale:
        session.commit()
    return len(stale)


def _claim(session: Session) -> FairEvaluation | None:
    candidates = session.scalars(
        select(FairEvaluation.id)
        .where(FairEvaluation.status == PENDING)
        .order_by(FairEvaluation.created_at.asc())
        .limit(5)
    ).all()
    for evaluation_id in candidates:
        result = session.execute(
            update(FairEvaluation)
            .where(FairEvaluation.id == evaluation_id, FairEvaluation.status == PENDING)
            .values(status=RUNNING, started_at=datetime.now(UTC))
        )
        session.commit()
        if result.rowcount == 1:  # type: ignore[attr-defined]
            return session.get(FairEvaluation, evaluation_id)
    return None


def evaluate_one(session: Session, settings: Settings, client: FujiClient) -> bool:
    """Reclama y evalúa una pendiente. Devuelve ``False`` si no había ninguna."""
    row = _claim(session)
    if row is None:
        return False
    url = evaluation_target(settings, row.version_uri)
    row.evaluated_url = url
    try:
        report = client.evaluate(url, f"{settings.fair_base_url}sparql")
        scores = parse_report(report)
    except FujiError as exc:
        row.status, row.error = FAILED, exc.message
    except Exception:
        logger.exception("Error inesperado al evaluar %s con F-UJI", row.version_uri)
        row.status, row.error = FAILED, ERROR_UNEXPECTED
    else:
        row.status = DONE
        row.report = report
        row.score_total = scores.total
        row.score_f = scores.findable
        row.score_a = scores.accessible
        row.score_i = scores.interoperable
        row.score_r = scores.reusable
        row.maturity = scores.maturity
        row.evaluator = scores.evaluator
        row.error = None
    row.finished_at = datetime.now(UTC)
    requester = session.get(User, row.requested_by) if row.requested_by else None
    audit.record(
        session,
        AuditAction.FAIR_EVALUATED,
        actor=requester,
        actor_username=None if requester else "cli",
        details={
            "evaluation": str(row.id),
            "version": row.version_uri,
            "status": row.status,
            "evaluated_url": url,
            "total": row.score_total,
        },
    )
    session.commit()
    return True


def process_pending(
    session_factory: sessionmaker[Session] | Callable[[], Session],
    settings: Settings,
    client: FujiClient | None = None,
    *,
    max_items: int = 100,
) -> int:
    """Evalúa las pendientes (hasta ``max_items``). Devuelve cuántas ha procesado."""
    client = client or FujiClient(settings)
    processed = 0
    with session_factory() as session:
        fail_stale(session, settings)
        while processed < max_items and evaluate_one(session, settings, client):
            processed += 1
    return processed


# --- Trabajador en segundo plano ----------------------------------------------------------

_wakeup = threading.Event()


def notify() -> None:
    """Despierta al trabajador (si está en este proceso) tras encolar algo."""
    _wakeup.set()


class FairWorker:
    """Hilo que procesa la cola. Sobrevive a cualquier error y a que F-UJI no esté."""

    def __init__(
        self,
        session_factory: Callable[[], sessionmaker[Session]],
        settings: Settings,
        client: FujiClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._client = client
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="fair-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        _wakeup.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                process_pending(self._session_factory(), self._settings, self._client)
            except Exception:
                logger.exception("El trabajador FAIR ha fallado; se reintenta más tarde")
            _wakeup.wait(self._settings.fair_worker_poll_seconds)
            _wakeup.clear()
