# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rdflib==7.6.0",
# ]
# ///
"""Genera los ficheros SINTÉTICOS de distribución (decisión 41, fase 4).

Uso (desde la raíz del repositorio):

    uv run semantic/scripts/ficheros_sinteticos.py

Lee las distribuciones de semantic/data/sintetico/*.ttl y escribe un fichero
por cada distribución cuyo dct:accessRights efectivo (el de la distribución
o, si no tiene, el de su versión) es PUBLIC o RESTRICTED, en

    semantic/data/sintetico/ficheros/{slug}/{version}/{dist}.{ext}

Nunca escribe fichero para una distribución NON_PUBLIC (defensa: solo
metadatos). Borra de esa carpeta lo que no corresponda a ninguna
distribución, para que el resultado dependa solo de los datos.

Los ficheros son mínimos (unos cientos de bytes), deterministas (sin fechas,
azar ni red: dos ejecuciones dan los mismos bytes) y marcados como
sintéticos con la cadena ASCII «SINTETICO» donde el formato lo permite. No
contienen BASE_URI ni ningún dominio: se identifican por su clave de
almacenamiento {slug}/{version}/{dist}. No reproducen tamaños, recuentos ni
columnas del prototipo, que siguen como placeholder.

El tipo de fichero sale del dcat:mediaType de la distribución (MEDIA_EXT).
Las distribuciones sin dcat:mediaType (NPZ, que no tiene tipo IANA) se
resuelven por el slug de la distribución (DIST_EXT_SIN_MEDIA). Los formatos
que exigirían una dependencia nueva quedan en PENDIENTES y no se generan.

semantic/scripts/validate.py importa este módulo para comprobar que los
ficheros del repositorio son exactamente los que genera.
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF

DEFAULT_BASE_URI = "https://semantic.example.org/itot/"
DCAT = Namespace("http://www.w3.org/ns/dcat#")
IANA = "http://www.iana.org/assignments/media-types/"
ACCESS_RIGHT = "http://publications.europa.eu/resource/authority/access-right/"

SEMANTIC_DIR = Path(__file__).resolve().parent.parent
SYNTHETIC_DIR = SEMANTIC_DIR / "data" / "sintetico"
FILES_DIR = SYNTHETIC_DIR / "ficheros"

# Tamaño máximo de un fichero sintético (contrato de la fase 4, 3.1).
MAX_BYTES = 64 * 1024
MARK = "SINTETICO"
NOTE = (
    "SINTETICO: fichero de prueba generado por semantic/scripts/ficheros_sinteticos.py. "
    "No contiene datos reales."
)

# Valores de dct:accessRights (tabla de autoridad de la UE) con y sin fichero.
WITH_FILE = {"PUBLIC", "RESTRICTED"}
WITHOUT_FILE = {"NON_PUBLIC"}

# dcat:mediaType (IANA) -> extensión.
MEDIA_EXT = {
    "application/vnd.tcpdump.pcap": "pcap",
    "text/csv": "csv",
    "application/vnd.apache.parquet": "parquet",
    "text/turtle": "ttl",
    "application/json": "json",
}
# Distribuciones sin dcat:mediaType: slug de la distribución -> extensión.
DIST_EXT_SIN_MEDIA = {"npz": "npz"}
# Formatos que no se generan todavía, con el motivo.
PENDIENTES = {
    "parquet": "escribir Parquet exige una dependencia nueva (p. ej. pyarrow); pendiente de decisión",
}


def base_uri() -> str:
    value = os.environ.get("BASE_URI", "").strip() or DEFAULT_BASE_URI
    return value if value.endswith("/") else value + "/"


@dataclass(frozen=True)
class Distribution:
    slug: str
    version: str
    dist: str
    uri: str
    media_type: str | None  # sin el prefijo IANA
    access: str | None  # PUBLIC, RESTRICTED, NON_PUBLIC… o None

    @property
    def key(self) -> str:
        """Clave de almacenamiento (contrato de la fase 4, sección 2)."""
        return f"{self.slug}/{self.version}/{self.dist}"

    @property
    def ext(self) -> str | None:
        if self.media_type is not None:
            return MEDIA_EXT.get(self.media_type)
        return DIST_EXT_SIN_MEDIA.get(self.dist)

    @property
    def needs_file(self) -> bool:
        return self.access in WITH_FILE

    @property
    def path(self) -> Path | None:
        """Ruta del fichero, o None si no lleva (NON_PUBLIC u otro acceso)."""
        if not self.needs_file or self.ext is None:
            return None
        return FILES_DIR / self.slug / self.version / f"{self.dist}.{self.ext}"


def _access(graph: Graph, node) -> str | None:
    value = graph.value(node, DCTERMS.accessRights)
    if value is None:
        return None
    text = str(value)
    return text[len(ACCESS_RIGHT):] if text.startswith(ACCESS_RIGHT) else text


def distributions(base: str) -> list[Distribution]:
    """Distribuciones de las versiones de semantic/data/sintetico/*.ttl."""
    found: list[Distribution] = []
    for path in sorted(SYNTHETIC_DIR.glob("*.ttl")):
        graph = Graph()
        graph.parse(path, format="turtle", publicID=base)
        for version in graph.subjects(RDF.type, DCAT.Dataset):
            serie = graph.value(version, DCAT.inSeries)
            number = graph.value(version, DCAT.version)
            if not isinstance(serie, URIRef) or number is None:
                continue
            slug = str(serie).rsplit("/", 1)[-1]
            version_access = _access(graph, version)
            for dist in graph.objects(version, DCAT.distribution):
                media = graph.value(dist, DCAT.mediaType)
                media_type = str(media)[len(IANA):] if media is not None and str(media).startswith(IANA) else None
                found.append(
                    Distribution(
                        slug=slug,
                        version=str(number),
                        dist=str(dist)[len(str(version)) + 1:],
                        uri=str(dist),
                        media_type=media_type,
                        access=_access(graph, dist) or version_access,
                    )
                )
    return sorted(found, key=lambda d: d.key)


# --- Generadores, uno por formato -------------------------------------------


def _csv(d: Distribution) -> bytes:
    # RFC 4180: CRLF y comillas dobles. CSV no tiene comentarios: la marca va
    # en la columna «sintetico» y en la nota.
    rows = [
        "sintetico,distribucion,nota",
        f'true,{d.key},"{NOTE}"',
    ]
    return ("\r\n".join(rows) + "\r\n").encode("utf-8")


def _json(d: Distribution) -> bytes:
    data = {"sintetico": True, "distribucion": d.key, "nota": NOTE}
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _turtle(d: Distribution) -> bytes:
    # Sin IRIs propias (no depende de BASE_URI): un nodo en blanco con la nota.
    text = (
        f"# {MARK}: distribución {d.key}.\n"
        f"# {NOTE}\n"
        "\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "\n"
        f'[] rdfs:label "{MARK} {d.key}" ;\n'
        f'   rdfs:comment "{NOTE}"@es .\n'
    )
    return text.encode("utf-8")


def _ipv4_checksum(header: bytes) -> int:
    total = sum(struct.unpack(f"!{len(header) // 2}H", header))
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _pcap(d: Distribution) -> bytes:
    """libpcap clásico (application/vnd.tcpdump.pcap), un único paquete.

    El formato clásico no tiene comentarios ni nombres de interfaz (eso es
    pcapng, que tiene otro tipo de medio): la marca va en la carga útil. El
    paquete es Ethernet/IPv4/UDP entre direcciones de documentación
    (192.0.2.0/24, RFC 5737) y MAC administradas localmente, puerto 9
    (discard), con marca de tiempo 0. No es tráfico Modbus.
    """
    payload = f"{NOTE} Distribucion {d.key}.".encode("ascii")
    udp = struct.pack("!HHHH", 9, 9, 8 + len(payload), 0) + payload  # checksum 0: opcional en IPv4
    ip = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
        bytes([192, 0, 2, 1]), bytes([192, 0, 2, 2]),
    )
    ip = ip[:10] + struct.pack("!H", _ipv4_checksum(ip)) + ip[12:]
    frame = bytes.fromhex("020000000002" "020000000001" "0800") + ip + udp
    header = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)  # LINKTYPE_ETHERNET
    record = struct.pack("<IIII", 0, 0, len(frame), len(frame))
    return header + record + frame


def _npy(data: bytes) -> bytes:
    """Un .npy versión 1.0 con un array 1-D de uint8 (formato de NumPy)."""
    header = f"{{'descr': '|u1', 'fortran_order': False, 'shape': ({len(data)},), }}"
    pad = 64 - (10 + len(header) + 1) % 64
    header = header + " " * (pad % 64) + "\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode("latin1") + data


def _npz(d: Distribution) -> bytes:
    """Archivo NPZ (zip sin comprimir de .npy, como numpy.savez) sin NumPy.

    Un array «SINTETICO» con los bytes de la nota, y la nota como comentario
    del zip. Fecha fija para que sea determinista.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        info = zipfile.ZipInfo(f"{MARK}.npy", date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        archive.writestr(info, _npy(f"{NOTE} Distribucion {d.key}.".encode("ascii")))
        archive.comment = f"{NOTE} Distribucion {d.key}.".encode("ascii")
    return buffer.getvalue()


GENERATORS = {"csv": _csv, "json": _json, "ttl": _turtle, "pcap": _pcap, "npz": _npz}


def content(d: Distribution) -> bytes | None:
    """Bytes del fichero de una distribución, o None si no se genera."""
    if d.path is None or d.ext in PENDIENTES:
        return None
    return GENERATORS[d.ext](d)


def expected_files(base: str) -> dict[Path, bytes]:
    return {d.path: data for d in distributions(base) if (data := content(d)) is not None}


def main() -> int:
    base = base_uri()
    expected = expected_files(base)
    for d in distributions(base):
        if d.access in WITHOUT_FILE:
            print(f"  sin fichero  {d.key} ({d.access}: solo metadatos)")
        elif not d.needs_file:
            print(f"  sin fichero  {d.key} (dct:accessRights {d.access!r} fuera de PUBLIC/RESTRICTED)")
        elif d.ext is None:
            print(f"  FALLO        {d.key}: no hay extensión para el tipo de medio {d.media_type!r}")
            return 1
        elif d.ext in PENDIENTES:
            print(f"  PENDIENTE    {d.key}.{d.ext}: {PENDIENTES[d.ext]}")
    for path, data in sorted(expected.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"  escrito      {path.relative_to(SEMANTIC_DIR.parent)} ({len(data)} bytes)")
    if FILES_DIR.is_dir():
        for path in sorted(FILES_DIR.rglob("*"), reverse=True):
            if path.is_file() and path not in expected:
                path.unlink()
                print(f"  borrado      {path.relative_to(SEMANTIC_DIR.parent)}")
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
