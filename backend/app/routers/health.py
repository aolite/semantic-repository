"""Health checks: vivo (``/health``) y listo (``/health/ready``)."""

from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from app.config import Settings
from app.deps import DbDep, SettingsDep
from app.schemas import ComponentStatus, HealthStatus, ReadinessStatus

router = APIRouter(prefix="/health", tags=["health"])

FUSEKI_TIMEOUT_SECONDS = 3.0


def check_fuseki(
    settings: Settings, transport: httpx.BaseTransport | None = None
) -> ComponentStatus:
    """Lanza ``ASK {}`` contra el dataset de Fuseki: comprueba servidor y dataset."""
    url = f"{settings.fuseki_url}/{settings.fuseki_dataset}/query"
    try:
        with httpx.Client(timeout=FUSEKI_TIMEOUT_SECONDS, transport=transport) as client:
            response = client.get(
                url,
                params={"query": "ASK {}"},
                headers={"Accept": "application/sparql-results+json"},
            )
    except httpx.HTTPError as exc:
        return ComponentStatus(status="error", detail=f"Fuseki no responde ({type(exc).__name__})")
    if response.status_code != status.HTTP_200_OK:
        return ComponentStatus(status="error", detail=f"Fuseki respondió {response.status_code}")
    return ComponentStatus(status="ok")


FusekiChecker = Callable[[Settings], ComponentStatus]


def get_fuseki_checker() -> FusekiChecker:
    return check_fuseki


@router.get("", response_model=HealthStatus, summary="El proceso está vivo")
def liveness() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessStatus,
    summary="La API puede atender: base de datos y Fuseki disponibles",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessStatus}},
)
def readiness(
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    fuseki_checker: Annotated[FusekiChecker, Depends(get_fuseki_checker)],
) -> ReadinessStatus:
    checks: dict[str, ComponentStatus] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = ComponentStatus(status="ok")
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de BD deja la API no lista
        checks["database"] = ComponentStatus(
            status="error", detail=f"Base de datos no disponible ({type(exc).__name__})"
        )
    checks["fuseki"] = fuseki_checker(settings)

    ready = all(check.status == "ok" for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessStatus(status="ok" if ready else "error", checks=checks)
