"""Pantalla «Vocabularios y ontologías»: tarjetas de ontologías y esquemas (lector anónimo)."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app import schemas, vocabularies
from app.deps import DbDep, StoreDep, UrisDep
from app.uris import SLUG_PATTERN, DomainSlug

router = APIRouter(prefix="/vocabularies", tags=["vocabularies"])


@router.get(
    "",
    response_model=schemas.VocabularyPage,
    summary="Tarjetas de ontologías propias y externas y de esquemas SKOS",
    description=(
        "Una tarjeta por ontología propia (con su versión actual), por ontología externa "
        "(estado `referenced`) y por esquema SKOS (corporativo o de dominio). `counts` es el "
        "recuento por tipo de todo el repositorio, para las tarjetas de estadísticas. Cada "
        "ontología propia y cada esquema dice su catálogo (`catalog`, decisión 50); los "
        "dados de baja no aparecen."
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
    domain: Annotated[
        DomainSlug | None,
        Query(
            description="Slug del dominio (it, ot, pqc, ia). Solo quedan las tarjetas con ese "
            "dominio: los esquemas de dominio cuyo dct:subject es el concepto del dominio"
        ),
    ] = None,
    catalog: Annotated[
        str | None,
        Query(
            pattern=SLUG_PATTERN,
            max_length=200,
            description="Solo las ontologías propias y los esquemas de este catálogo "
            "(catalogo/{slug}, decisión 50); las externas no están en ningún catálogo",
        ),
    ] = None,
) -> schemas.VocabularyPage:
    return vocabularies.list_vocabularies(
        store, db, uris, q=q, kind=kind, domain=domain, catalog=catalog
    )
