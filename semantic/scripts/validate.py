# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rdflib>=7.1,<8",
#     "pyshacl>=0.30,<1",
# ]
# ///
"""Valida el RDF de semantic/.

Uso (desde la raíz del repositorio, también en CI):

    uv run semantic/scripts/validate.py

Comprueba:
  1. Que todo .ttl de semantic/ se analiza sin errores y no declara @base
     (las URIs propias son relativas y se resuelven contra BASE_URI).
  2. Que las formas de semantic/shapes/ son SHACL válido (meta-SHACL).
  3. Que cada ejemplo de semantic/examples/valid/ cumple las formas.
  4. Que cada ejemplo de semantic/examples/invalid/ NO las cumple y que las
     formas que fallan son exactamente las de sus líneas
     «# expect-violation: <NombreLocal>».

Sale con código 0 si todo va bien y 1 si algo falla.

BASE_URI se lee del entorno; si no está, se usa el valor por defecto del
proyecto. Ver semantic/uris.md.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from pyshacl import validate
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

DEFAULT_BASE_URI = "https://semantic.example.org/itot/"
SH = Namespace("http://www.w3.org/ns/shacl#")

SEMANTIC_DIR = Path(__file__).resolve().parent.parent
SHAPES_DIR = SEMANTIC_DIR / "shapes"
VALID_DIR = SEMANTIC_DIR / "examples" / "valid"
INVALID_DIR = SEMANTIC_DIR / "examples" / "invalid"

BASE_DECL = re.compile(r"^\s*(@base|BASE)\s", re.IGNORECASE | re.MULTILINE)
EXPECT = re.compile(r"^#\s*expect-violation:\s*(\S+)\s*$", re.MULTILINE)


def base_uri() -> str:
    value = os.environ.get("BASE_URI", "").strip() or DEFAULT_BASE_URI
    return value if value.endswith("/") else value + "/"


def rel(path: Path) -> str:
    return str(path.relative_to(SEMANTIC_DIR.parent))


def parse(path: Path, base: str) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle", publicID=base)
    return graph


def failing_shapes(results: Graph, shapes_ns: str) -> set[str]:
    """Nombres locales de las formas que han producido algún resultado."""
    names = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        shape = results.value(result, SH.sourceShape)
        if isinstance(shape, URIRef) and str(shape).startswith(shapes_ns):
            names.add(str(shape)[len(shapes_ns):])
        else:
            names.add(f"<forma sin nombre: {shape}>")
    return names


def main() -> int:
    base = base_uri()
    shapes_ns = base + "shapes#"
    errors: list[str] = []
    print(f"BASE_URI = {base}")

    # 1. Sintaxis de todo .ttl y ausencia de @base.
    ttl_files = sorted(SEMANTIC_DIR.rglob("*.ttl"))
    print(f"\n[1] Sintaxis Turtle ({len(ttl_files)} ficheros)")
    for path in ttl_files:
        text = path.read_text(encoding="utf-8")
        if BASE_DECL.search(text):
            errors.append(f"{rel(path)}: declara @base; las URIs propias deben ser relativas a BASE_URI")
            print(f"  FALLO  {rel(path)} (declara @base)")
            continue
        try:
            parse(path, base)
            print(f"  ok     {rel(path)}")
        except Exception as exc:  # noqa: BLE001 - cualquier error de análisis cuenta
            errors.append(f"{rel(path)}: error de sintaxis: {exc}")
            print(f"  FALLO  {rel(path)}: {exc}")

    # 2. Formas SHACL.
    shape_files = sorted(SHAPES_DIR.glob("*.ttl"))
    print(f"\n[2] Formas SHACL ({len(shape_files)} ficheros)")
    if not shape_files:
        errors.append("no hay formas en semantic/shapes/")
        return report(errors)
    shapes = Graph()
    try:
        for path in shape_files:
            shapes += parse(path, base)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"no se pueden cargar las formas: {exc}")
        return report(errors)
    empty = Graph()
    try:
        validate(empty, shacl_graph=shapes, meta_shacl=True, inference="none")
        print("  ok     las formas cumplen meta-SHACL")
    except Exception as exc:  # noqa: BLE001 - pyshacl lanza si meta-SHACL falla
        errors.append(f"las formas no son SHACL válido: {exc}")
        print(f"  FALLO  meta-SHACL: {exc}")
        return report(errors)

    def run(path: Path) -> tuple[bool, Graph, str] | None:
        try:
            data = parse(path, base)
        except Exception:  # noqa: BLE001 - ya informado en el paso 1
            return None
        conforms, results, text = validate(
            data,
            shacl_graph=shapes,
            inference="none",
            abort_on_first=False,
            allow_warnings=False,
        )
        return conforms, results, text

    # 3. Ejemplos válidos.
    valid_files = sorted(VALID_DIR.glob("*.ttl"))
    print(f"\n[3] Ejemplos válidos ({len(valid_files)} ficheros)")
    if not valid_files:
        errors.append("no hay ejemplos en semantic/examples/valid/")
    for path in valid_files:
        outcome = run(path)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, _, text = outcome
        if conforms:
            print(f"  ok     {rel(path)}")
        else:
            errors.append(f"{rel(path)}: debería cumplir las formas y no las cumple")
            print(f"  FALLO  {rel(path)}\n{text}")

    # 4. Ejemplos inválidos.
    invalid_files = sorted(INVALID_DIR.glob("*.ttl"))
    print(f"\n[4] Ejemplos inválidos ({len(invalid_files)} ficheros)")
    if not invalid_files:
        errors.append("no hay ejemplos en semantic/examples/invalid/")
    for path in invalid_files:
        expected = set(EXPECT.findall(path.read_text(encoding="utf-8")))
        if not expected:
            errors.append(f"{rel(path)}: falta la línea «# expect-violation: <NombreLocal>»")
            print(f"  FALLO  {rel(path)} (sin expect-violation)")
            continue
        outcome = run(path)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, results, text = outcome
        if conforms:
            errors.append(f"{rel(path)}: debería fallar y cumple las formas")
            print(f"  FALLO  {rel(path)} (cumple las formas)")
            continue
        got = failing_shapes(results, shapes_ns)
        if got == expected:
            print(f"  ok     {rel(path)} falla en {', '.join(sorted(got))}")
        else:
            errors.append(
                f"{rel(path)}: se esperaba que fallara {sorted(expected)} y falla {sorted(got)}"
            )
            print(f"  FALLO  {rel(path)}: esperado {sorted(expected)}, obtenido {sorted(got)}\n{text}")

    return report(errors)


def report(errors: list[str]) -> int:
    if errors:
        print(f"\nValidación FALLIDA ({len(errors)} errores):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("\nValidación correcta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
