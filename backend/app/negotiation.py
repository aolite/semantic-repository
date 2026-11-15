"""Negociación de contenido sencilla según la cabecera ``Accept`` (RFC 9110, sección 12.5.1).

Se elige, de entre los tipos que ofrece el servidor, el de mayor ``q``. Con empate gana
el orden en que el servidor los ofrece. Sin ``Accept`` (o con ``*/*``) se devuelve el
primero ofrecido.
"""

from dataclasses import dataclass

TURTLE = "text/turtle"
JSONLD = "application/ld+json"
HTML = "text/html"
RDFXML = "application/rdf+xml"


@dataclass(frozen=True)
class _Range:
    type: str
    subtype: str
    q: float
    order: int

    def matches(self, media_type: str) -> int:
        """Especificidad de la coincidencia (2 exacta, 1 tipo/*, 0 */*); -1 si no casa."""
        main, _, sub = media_type.partition("/")
        if self.type == "*" and self.subtype == "*":
            return 0
        if self.type == main and self.subtype == "*":
            return 1
        if self.type == main and self.subtype == sub:
            return 2
        return -1


def _parse(header: str) -> list[_Range]:
    ranges = []
    for order, part in enumerate(header.split(",")):
        pieces = [p.strip() for p in part.split(";")]
        media = pieces[0].lower()
        if "/" not in media:
            continue
        main, _, sub = media.partition("/")
        q = 1.0
        for param in pieces[1:]:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    q = max(0.0, min(1.0, float(value.strip())))
                except ValueError:
                    q = 0.0
        ranges.append(_Range(main, sub, q, order))
    return ranges


def negotiate(accept: str | None, offered: list[str]) -> str | None:
    """Tipo elegido de ``offered`` o ``None`` si ninguno es aceptable (406)."""
    if not accept or not accept.strip():
        return offered[0]
    ranges = _parse(accept)
    if not ranges:
        return offered[0]
    best: tuple[float, int, int] | None = None
    chosen: str | None = None
    for index, media_type in enumerate(offered):
        # El rango más específico que casa decide la q de este tipo.
        matching = [(r.matches(media_type), r) for r in ranges if r.matches(media_type) >= 0]
        if not matching:
            continue
        specificity, rng = max(matching, key=lambda item: (item[0], -item[1].order))
        if rng.q <= 0:
            continue
        score = (rng.q, specificity, -index)
        if best is None or score > best:
            best, chosen = score, media_type
    return chosen
