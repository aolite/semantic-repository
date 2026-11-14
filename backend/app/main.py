"""Aplicación FastAPI del repositorio semántico IT&OT."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import Settings, get_settings
from app.routers import auth, health, users

API_TITLE = "Repositorio semántico IT&OT · API"
API_DESCRIPTION = (
    "API del catálogo DCAT-AP del repositorio semántico IT&OT. "
    "Fase 1: health checks, autenticación JWT y gestión de cuentas."
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

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    return app


app = create_app()
