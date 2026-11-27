"""Backend del repositorio semántico IT&OT."""

import tomllib
from pathlib import Path

PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _read_version() -> str:
    """Versión del backend: única fuente, ``project.version`` de ``pyproject.toml``.

    El proyecto no se instala como paquete (``[tool.uv] package = false``), así que no hay
    metadatos de distribución: se lee el fichero, que la imagen Docker copia junto a ``app/``.
    """
    with PYPROJECT_PATH.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


__version__ = _read_version()
