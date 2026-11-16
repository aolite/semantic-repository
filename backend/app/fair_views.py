"""Datos de la ficha y del catálogo que no están en el triplestore (fase 4).

- Ficheros de distribución (``distribution_files``): ``download``, ``download_url``,
  ``byte_size`` y ``sha256`` de cada ``DistributionRead``.
- Evaluación FAIR (``fair_evaluations``): ``VersionDetail.fair`` y
  ``DatasetCard.fair_total``.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app import distributions, fair, schemas
from app.uris import Uris


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:  # SQLite no guarda la zona horaria
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


def report_path(slug: str, version: str) -> str:
    return f"/datasets/{slug}/versions/{version}/fair/report"


def fair_summary(
    session: Session, slug: str, version: str, version_uri: str
) -> schemas.FairSummary:
    """Estado de la evaluación más reciente; datos de la última ``done``."""
    last = fair.latest(session, version_uri)
    done = fair.latest_done(session, version_uri)
    status = last.status if last is not None else "not_evaluated"
    return schemas.FairSummary(
        status=status,  # type: ignore[arg-type]
        total=done.score_total if done else None,
        findable=done.score_f if done else None,
        accessible=done.score_a if done else None,
        interoperable=done.score_i if done else None,
        reusable=done.score_r if done else None,
        maturity=done.maturity if done else None,
        evaluator=done.evaluator if done else None,
        evaluated_at=_iso(done.finished_at) if done else None,
        report_url=report_path(slug, version) if done and done.report is not None else None,
    )


def enrich_version(session: Session, uris: Uris, slug: str, detail: schemas.VersionDetail) -> None:
    version = detail.version
    if not version:
        return
    version_uri = uris.version(slug, version)
    prefix = f"{version_uri}/"
    files = distributions.files_by_uri(session, [d.uri for d in detail.distributions])
    for dist in detail.distributions:
        record = files.get(dist.uri)
        code = dist.access_rights.code if dist.access_rights else None
        dist.download = distributions.download_mode(code, record is not None)
        segment = dist.uri[len(prefix) :] if dist.uri.startswith(prefix) else ""
        if dist.download in ("open", "authenticated") and segment:
            # Ruta del fichero de la sección 2 del contrato: {BASE_URI}dataset/…/fichero.
            dist.download_url = f"{prefix}{segment}/{distributions.FILE_SEGMENT}"
        if record is not None and dist.download != "metadata_only":
            dist.byte_size = record.byte_size
            dist.sha256 = record.sha256
    detail.fair = fair_summary(session, slug, version, detail.uri)


def add_fair_totals(session: Session, uris: Uris, cards: list[schemas.DatasetCard]) -> None:
    current = {
        card.slug: uris.version(card.slug, card.current_version)
        for card in cards
        if card.current_version
    }
    totals = fair.latest_done_totals(session, list(current.values()))
    for card in cards:
        uri = current.get(card.slug)
        card.fair_total = totals.get(uri) if uri else None
