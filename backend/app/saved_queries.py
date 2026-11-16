"""Consultas guardadas de la Consola SPARQL (decisión 43).

- **De referencia:** ficheros ``SEMANTIC_DIR/consultas/{id}.rq`` de ``semantico``, visibles
  para todos. Empiezan con una cabecera de comentarios ``# title: …`` y ``# hint: …``; los
  IRIs propios llevan el marcador ``{BASE_URI}``, que aquí se sustituye por ``BASE_URI``.
  El ``id`` es el nombre del fichero (un slug). Se devuelve el texto sin las líneas
  ``title`` y ``hint`` (el resto de comentarios se conserva).
- **Personales:** tabla ``saved_queries``, visibles solo para su dueño.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.uris import is_slug

logger = logging.getLogger(__name__)

QUERIES_DIR = Path("consultas")
BASE_URI_MARKER = "{BASE_URI}"
MAX_REFERENCE_BYTES = 20 * 1024
_HEADER = re.compile(r"^#\s*(title|hint)\s*:\s*(.*?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ReferenceQuery:
    id: str
    title: str
    hint: str | None
    query: str


def parse_reference(slug: str, text: str, base_uri: str) -> ReferenceQuery | None:
    title: str | None = None
    hint: str | None = None
    body: list[str] = []
    in_header = True
    for line in text.splitlines():
        match = _HEADER.match(line) if in_header else None
        if match:
            if match.group(1).lower() == "title":
                title = match.group(2)
            else:
                hint = match.group(2) or None
            continue
        if in_header and not line.lstrip().startswith("#"):
            in_header = False
        body.append(line)
    if not title:
        return None
    query = "\n".join(body).strip("\n").replace(BASE_URI_MARKER, base_uri) + "\n"
    return ReferenceQuery(
        id=slug, title=title[:120], hint=hint[:200] if hint else None, query=query
    )


def load_references(semantic_dir: Path, base_uri: str) -> list[ReferenceQuery]:
    """Consultas de referencia en orden alfabético de ``id``. Las no válidas se omiten."""
    folder = semantic_dir / QUERIES_DIR
    if not folder.is_dir():
        return []
    result = []
    for path in sorted(folder.glob("*.rq")):
        if not is_slug(path.stem) or not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_REFERENCE_BYTES:
                logger.warning("Consulta de referencia demasiado grande: %s", path.name)
                continue
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            logger.warning("No se puede leer la consulta de referencia %s", path.name)
            continue
        reference = parse_reference(path.stem, text, base_uri)
        if reference is None:
            logger.warning("Consulta de referencia sin '# title:': %s", path.name)
            continue
        result.append(reference)
    return sorted(result, key=lambda r: r.id)
