"""Aplicación FastAPI del repositorio semántico IT&OT."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__, fair
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.routers import (
    auth,
    catalogs,
    dataset_files,
    datasets,
    externals,
    gone,
    health,
    linked_data,
    linked_data_vocab,
    ontologies,
    schemes,
    sparql,
    users,
    vocabularies,
)
from app.triplestore import TriplestoreError
from app.write_lock import CatalogLockTimeoutError

API_TITLE = "Repositorio semántico IT&OT · API"
API_DESCRIPTION = (
    "API del catálogo DCAT-AP del repositorio semántico IT&OT. "
    "Fase 1: health checks, autenticación JWT y gestión de cuentas. "
    "Fase 2: lectura del catálogo, ingesta validada con SHACL y negociación de contenido "
    "en las URIs persistentes. "
    "Fase 3: ingesta y lectura de ontologías (con métricas OWL y consistencia) y de esquemas "
    "SKOS, y negociación en sus URIs persistentes. "
    "Fase 4: versiones inmutables, ficheros de distribución con acceso por rol, evaluación "
    "FAIR con F-UJI, SPARQL público con límites, consultas guardadas y bloqueo de login."
)

# Cabeceras que el navegador puede leer en respuestas CORS (aviso de truncado del SPARQL,
# espera de un 429 y nombre del fichero descargado).
EXPOSED_HEADERS = ["X-Result-Truncated", "Retry-After", "Content-Disposition"]


# Claves de cada error de validación que se devuelven al cliente. Se omiten ``input`` y
# ``ctx``, que pueden contener el valor enviado (por ejemplo, una contraseña).
_VALIDATION_ERROR_KEYS = ("type", "loc", "msg")


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 con el formato estándar de FastAPI, pero sin devolver los valores enviados."""
    errors = [
        {key: error[key] for key in _VALIDATION_ERROR_KEYS if key in error}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(errors)},
    )


async def catalog_lock_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """503 si el bloqueo de escritura del catálogo no llega a tiempo (QA-49-03)."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
        headers={"Retry-After": "5"},
    )


async def triplestore_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """503 si Fuseki no responde o falta configuración. El mensaje no incluye secretos."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea la aplicación. Valida la configuración: sin ``JWT_SECRET`` no arranca."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Trabajador de las evaluaciones FAIR (F-UJI). FAIR_WORKER_POLL_SECONDS=0 lo apaga
        # (pruebas). Si F-UJI no está, las evaluaciones quedan failed; la API sigue.
        worker = None
        if settings.fair_worker_poll_seconds > 0:
            worker = fair.FairWorker(get_sessionmaker, settings)
            worker.start()
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()

    app = FastAPI(
        title=API_TITLE, description=API_DESCRIPTION, version=__version__, lifespan=lifespan
    )

    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Accept"],
            expose_headers=EXPOSED_HEADERS,
        )

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(TriplestoreError, triplestore_exception_handler)
    app.add_exception_handler(gone.GoneError, gone.gone_exception_handler)
    app.add_exception_handler(CatalogLockTimeoutError, catalog_lock_exception_handler)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(catalogs.router)
    app.include_router(datasets.router)
    app.include_router(dataset_files.router)
    app.include_router(sparql.router)
    app.include_router(linked_data.router)
    app.include_router(linked_data.catalog_router)
    app.include_router(vocabularies.router)
    app.include_router(externals.router)  # antes que /ontologies/{slug}/rdf
    app.include_router(ontologies.router)
    app.include_router(schemes.router)
    app.include_router(linked_data_vocab.onto_router)
    app.include_router(linked_data_vocab.vocab_router)
    return app


app = create_app()
