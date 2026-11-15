"""Aplicación FastAPI del repositorio semántico IT&OT."""

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import Settings, get_settings
from app.routers import (
    auth,
    datasets,
    health,
    linked_data,
    linked_data_vocab,
    ontologies,
    schemes,
    users,
    vocabularies,
)
from app.triplestore import TriplestoreError

API_TITLE = "Repositorio semántico IT&OT · API"
API_DESCRIPTION = (
    "API del catálogo DCAT-AP del repositorio semántico IT&OT. "
    "Fase 1: health checks, autenticación JWT y gestión de cuentas. "
    "Fase 2: lectura del catálogo, ingesta validada con SHACL y negociación de contenido "
    "en las URIs persistentes. "
    "Fase 3: ingesta y lectura de ontologías (con métricas OWL y consistencia) y de esquemas "
    "SKOS, y negociación en sus URIs persistentes."
)


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


async def triplestore_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """503 si Fuseki no responde o falta configuración. El mensaje no incluye secretos."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea la aplicación. Valida la configuración: sin ``JWT_SECRET`` no arranca."""
    settings = settings or get_settings()

    app = FastAPI(title=API_TITLE, description=API_DESCRIPTION, version=__version__)

    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Accept"],
        )

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(TriplestoreError, triplestore_exception_handler)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(datasets.router)
    app.include_router(linked_data.router)
    app.include_router(vocabularies.router)
    app.include_router(ontologies.router)
    app.include_router(schemes.router)
    app.include_router(linked_data_vocab.onto_router)
    app.include_router(linked_data_vocab.vocab_router)
    return app


app = create_app()
