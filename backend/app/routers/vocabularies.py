"""Pantalla «Vocabularios y ontologías»: tarjetas de ontologías y esquemas (lector anónimo)."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app import schemas, vocabularies
from app.deps import DbDep, StoreDep, UrisDep

router = APIRouter(prefix="/vocabularies", tags=["vocabularies"])


@router.get(
    "",
    response_model=schemas.VocabularyPage,
    summary="Tarjetas de ontologías propias y externas y de esquemas SKOS",
    description=(
        "Una tarjeta por ontología propia (con su versión actual), por ontología externa "
        "(estado `referenced`) y por esquema SKOS (corporativo o de dominio). `counts` es el "
        "recuento por tipo de todo el repositorio, para las tarjetas de estadísticas."
    ),
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": schemas.ErrorResponse}},
)
def list_vocabularies(
    store: StoreDep,
    db: DbDep,
    uris: UrisDep,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Texto en el nombre, el prefijo o el espacio de nombres (sin distinguir "
            "mayúsculas ni acentos)",
        ),
    ] = None,
    kind: Annotated[schemas.VocabularyKind | None, Query(description="Tipo de tarjeta")] = None,
) -> schemas.VocabularyPage:
    return vocabularies.list_vocabularies(store, db, uris, q=q, kind=kind)
