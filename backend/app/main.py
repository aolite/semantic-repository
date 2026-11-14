"""Aplicación FastAPI del repositorio semántico IT&OT."""

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import Settings, get_settings
from app.routers import auth, health, users

API_TITLE = "Repositorio semántico IT&OT · API"
API_DESCRIPTION = (
    "API del catálogo DCAT-AP del repositorio semántico IT&OT. "
    "Fase 1: health checks, autenticación JWT y gestión de cuentas."
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

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    return app


app = create_app()
