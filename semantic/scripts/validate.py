# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rdflib==7.6.0",
#     "pyshacl==0.40.2",
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
  4. Que cada ejemplo de semantic/examples/invalid/ (y de su subcarpeta
     ontologias-vocabularios/) NO las cumple y que las
     formas que fallan son exactamente las de sus líneas
     «# expect-violation: <NombreLocal>».
  5. Que cada fichero de semantic/data/sintetico/ (lo que ingesta el backend,
     un fichero por dataset) cumple las formas por sí solo.
  6. Que todo semantic/data/**/*.ttl junto (datos, catálogo y esquemas
     auxiliares en un grafo) cumple las formas y es coherente: temas que son
     conceptos de esquemas de dominio (semantic/vocabularios/) y de un único
     dominio, marca de sintético, referencias entre series, versiones y
     distribuciones, y URIs según semantic/uris.md.
  7. Que cada esquema de semantic/vocabularios/ (un fichero, un esquema, un
     grafo con nombre) cumple las formas por sí solo y es coherente: URI
     según la ruta del fichero, dominio (dct:subject) en los de dominio y no
     en los corporativos, marca de sintético y prefijos VANN únicos.
  8. Que cada versión de semantic/ontologias/{slug}/{version}.ttl y
     semantic/ontologias/externas.ttl cumplen las formas por sí solos y son
     coherentes: URIs según la ruta, cadena de owl:priorVersion, términos en
     su espacio de nombres, imports y alineamientos hacia ontologías
     externas catalogadas y dct:subject hacia conceptos existentes.

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
from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS

DEFAULT_BASE_URI = "https://semantic.example.org/itot/"
SH = Namespace("http://www.w3.org/ns/shacl#")
# Namespace propio: el DCAT de rdflib no incluye los términos de DCAT 3.
DCAT = Namespace("http://www.w3.org/ns/dcat#")

SEMANTIC_DIR = Path(__file__).resolve().parent.parent
SHAPES_DIR = SEMANTIC_DIR / "shapes"
VALID_DIR = SEMANTIC_DIR / "examples" / "valid"
INVALID_DIR = SEMANTIC_DIR / "examples" / "invalid"
DATA_DIR = SEMANTIC_DIR / "data"
SYNTHETIC_DIR = DATA_DIR / "sintetico"
AUX_VOCAB_FILE = DATA_DIR / "vocab-minimo.ttl"
VOCAB_DIR = SEMANTIC_DIR / "vocabularios"
CORP_DIR = VOCAB_DIR / "corp"
ONTO_DIR = SEMANTIC_DIR / "ontologias"
EXTERNAL_FILE = ONTO_DIR / "externas.ttl"

VANN = Namespace("http://purl.org/vocab/vann/")
ADMS = Namespace("http://www.w3.org/ns/adms#")

# Dominios del catálogo: conceptos {BASE_URI}vocab/dominio/{slug}
# (semantic/uris.md) y marca de sintético.
DOMAIN_SLUGS = ("it", "ot", "pqc", "ia")
SYNTHETIC_TYPE = "vocab/tipo-dataset/sintetico"
# Segmentos de vocab/ que no pueden ser slug de un esquema de dominio.
RESERVED_VOCAB_SLUGS = ("corp", "dominio", "tipo-dataset")
# Mientras todo el contenido de ontologias/ y vocabularios/ sea sintético
# (hasta el piloto), cada ontología propia y cada esquema lleva la marca.
REQUIRE_SYNTHETIC_MARK = True

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

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
    # Raíz: datasets (los que el backend pasa por su ingesta de datasets).
    # Subcarpeta ontologias-vocabularios/: esquemas SKOS y ontologías.
    invalid_files = sorted(INVALID_DIR.rglob("*.ttl"))
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

    # 5. Datos sintéticos, fichero a fichero.
    synthetic_files = sorted(SYNTHETIC_DIR.glob("*.ttl"))
    print(f"\n[5] Datos sintéticos, uno a uno ({len(synthetic_files)} ficheros)")
    if not synthetic_files:
        errors.append("no hay datos en semantic/data/sintetico/")
    for path in synthetic_files:
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

    # 6. Todo semantic/data/ en un grafo: formas y coherencia.
    data_files = sorted(DATA_DIR.rglob("*.ttl"))
    print(f"\n[6] semantic/data/ en un grafo ({len(data_files)} ficheros)")
    combined = Graph()
    try:
        for path in data_files:
            combined.parse(path, format="turtle", publicID=base)
    except Exception as exc:  # noqa: BLE001 - ya informado en el paso 1
        errors.append(f"semantic/data/: no se puede cargar: {exc}")
        return report(errors)
    conforms, _, text = validate(
        combined, shacl_graph=shapes, inference="none", abort_on_first=False, allow_warnings=False
    )
    if conforms:
        print("  ok     cumple las formas")
    else:
        errors.append("semantic/data/: el grafo conjunto no cumple las formas")
        print(f"  FALLO  formas\n{text}")
    synthetic_subjects: set[URIRef] = set()
    for path in synthetic_files:
        graph = parse(path, base)
        for cls in (DCAT.Dataset, DCAT.DatasetSeries):
            synthetic_subjects.update(s for s in graph.subjects(RDF.type, cls) if isinstance(s, URIRef))
    # Vocabulario completo (esquemas auxiliares y todos los de vocabularios/),
    # para comprobar los temas de los datasets y los dct:subject.
    vocab_files = sorted(VOCAB_DIR.rglob("*.ttl"))
    vocab = Graph()
    try:
        vocab += parse(AUX_VOCAB_FILE, base)
        for path in vocab_files:
            vocab += parse(path, base)
    except Exception as exc:  # noqa: BLE001 - ya informado en el paso 1
        errors.append(f"semantic/vocabularios/: no se puede cargar: {exc}")
        return report(errors)

    problems = coherence(combined, base, synthetic_subjects, vocab)
    for problem in problems:
        errors.append(f"semantic/data/: {problem}")
        print(f"  FALLO  {problem}")
    if not problems:
        print("  ok     coherencia (dominios, marca de sintético, referencias y URIs)")

    # 7. Esquemas SKOS, uno a uno: formas y coherencia.
    print(f"\n[7] Esquemas SKOS de semantic/vocabularios/, uno a uno ({len(vocab_files)} ficheros)")
    if not vocab_files:
        errors.append("no hay esquemas en semantic/vocabularios/")
    prefixes: dict[str, list[str]] = {}
    for path in vocab_files:
        outcome = run(path)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, _, text = outcome
        problems = scheme_coherence(path, parse(path, base), base, vocab, prefixes)
        if not conforms:
            errors.append(f"{rel(path)}: debería cumplir las formas y no las cumple")
            print(f"  FALLO  {rel(path)}\n{text}")
        for problem in problems:
            errors.append(f"{rel(path)}: {problem}")
            print(f"  FALLO  {rel(path)}: {problem}")
        if conforms and not problems:
            print(f"  ok     {rel(path)}")

    # 8. Ontologías, versión a versión, y externas: formas y coherencia.
    onto_files = sorted(p for p in ONTO_DIR.rglob("*.ttl") if p != EXTERNAL_FILE)
    print(f"\n[8] Ontologías de semantic/ontologias/ ({len(onto_files)} versiones y externas.ttl)")
    if not onto_files:
        errors.append("no hay ontologías propias en semantic/ontologias/")
    if not EXTERNAL_FILE.exists():
        errors.append(f"falta {rel(EXTERNAL_FILE)}")
        return report(errors)
    external = parse(EXTERNAL_FILE, base)
    for path in [*onto_files, EXTERNAL_FILE]:
        outcome = run(path)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, _, text = outcome
        graph = parse(path, base)
        if path == EXTERNAL_FILE:
            problems = external_coherence(graph, base, prefixes)
        else:
            problems = ontology_coherence(path, graph, base, vocab, external, onto_files, prefixes)
        if not conforms:
            errors.append(f"{rel(path)}: debería cumplir las formas y no las cumple")
            print(f"  FALLO  {rel(path)}\n{text}")
        for problem in problems:
            errors.append(f"{rel(path)}: {problem}")
            print(f"  FALLO  {rel(path)}: {problem}")
        if conforms and not problems:
            print(f"  ok     {rel(path)}")

    # Prefijos VANN únicos entre esquemas y ontologías (las versiones de una
    # misma ontología comparten el suyo).
    for prefix, owners in sorted(prefixes.items()):
        if len(set(owners)) > 1:
            errors.append(f"prefijo VANN «{prefix}» repetido en {', '.join(sorted(set(owners)))}")
            print(f"  FALLO  prefijo VANN «{prefix}» repetido en {', '.join(sorted(set(owners)))}")

    return report(errors)


def short_of(base: str):
    def short(node) -> str:
        return str(node)[len(base):] if str(node).startswith(base) else str(node)

    return short


def domain_of(vocab: Graph, base: str, concept) -> set[URIRef]:
    """Dominios (conceptos de vocab/dominio) del esquema de un concepto."""
    domains = {URIRef(f"{base}vocab/dominio/{slug}") for slug in DOMAIN_SLUGS}
    found: set[URIRef] = set()
    for scheme in vocab.objects(concept, SKOS.inScheme):
        found |= set(vocab.objects(scheme, DCTERMS.subject)) & domains
    return found


def scheme_coherence(path: Path, g: Graph, base: str, vocab: Graph, prefixes: dict[str, list[str]]) -> list[str]:
    """Un fichero de vocabularios/: URI según la ruta, dominio y contenido.

    La ruta decide el tipo: vocabularios/{slug}.ttl es un esquema de dominio
    ({BASE_URI}vocab/{slug}, con dct:subject) y vocabularios/corp/{slug}.ttl,
    uno corporativo ({BASE_URI}vocab/corp/{slug}, sin dct:subject).
    """
    problems: list[str] = []
    short = short_of(base)
    slug = path.stem
    corporate = path.parent == CORP_DIR
    if path.parent not in (VOCAB_DIR, CORP_DIR):
        return [f"ubicación no prevista; los esquemas van en {rel(VOCAB_DIR)}/ o {rel(CORP_DIR)}/"]
    if not SLUG.match(slug):
        problems.append(f"el nombre del fichero no es un slug válido ({slug})")
    if not corporate and slug in RESERVED_VOCAB_SLUGS:
        problems.append(f"«{slug}» es un segmento reservado de vocab/")
    expected = URIRef(f"{base}vocab/corp/{slug}" if corporate else f"{base}vocab/{slug}")
    schemes = set(g.subjects(RDF.type, SKOS.ConceptScheme))
    if schemes != {expected}:
        problems.append(f"tiene que describir exactamente un skos:ConceptScheme, {short(expected)}; describe {sorted(map(short, schemes))}")
        return problems

    domains = {URIRef(f"{base}vocab/dominio/{s}") for s in DOMAIN_SLUGS}
    subjects = set(g.objects(expected, DCTERMS.subject))
    if corporate and subjects:
        problems.append("un esquema corporativo no lleva dominio (dct:subject)")
    if not corporate and (len(subjects) != 1 or not subjects <= domains):
        problems.append(f"un esquema de dominio declara exactamente un dct:subject de vocab/dominio/{{{'|'.join(DOMAIN_SLUGS)}}}")
    for value in g.objects(expected, DCTERMS.type):
        if (value, RDF.type, SKOS.Concept) not in vocab:
            problems.append(f"dct:type {short(value)} no es un skos:Concept del vocabulario")
    if REQUIRE_SYNTHETIC_MARK and (expected, DCTERMS.type, URIRef(base + SYNTHETIC_TYPE)) not in g:
        problems.append(f"falta dct:type <{SYNTHETIC_TYPE}>")

    # Todo sujeto con IRI bajo BASE_URI es el esquema o uno de sus conceptos:
    # un fichero no puede describir recursos de otro grafo.
    for subject in set(g.subjects()):
        if isinstance(subject, BNode) or not str(subject).startswith(base) or subject == expected:
            continue
        if (subject, SKOS.inScheme, expected) not in g:
            problems.append(f"describe {short(subject)}, que no es un concepto de este esquema")

    for prefix in g.objects(expected, VANN.preferredNamespacePrefix):
        prefixes.setdefault(str(prefix), []).append(rel(path))
    return problems


def ontology_coherence(
    path: Path,
    g: Graph,
    base: str,
    vocab: Graph,
    external: Graph,
    all_versions: list[Path],
    prefixes: dict[str, list[str]],
) -> list[str]:
    """Una versión de ontología propia: ontologias/{slug}/{version}.ttl."""
    problems: list[str] = []
    short = short_of(base)
    slug, version = path.parent.name, path.stem
    if path.parent.parent != ONTO_DIR or not SLUG.match(slug) or not SEMVER.match(version):
        return [f"ubicación no prevista; las versiones van en {rel(ONTO_DIR)}/{{slug}}/{{version}}.ttl"]
    onto = URIRef(f"{base}onto/{slug}")
    ontologies = set(g.subjects(RDF.type, OWL.Ontology))
    if ontologies != {onto}:
        return [f"tiene que describir exactamente una owl:Ontology, {short(onto)}; describe {sorted(map(short, ontologies))}"]

    # versionIRI y versionInfo según la ruta (las formas comprueban que
    # versionIRI = URI/versionInfo).
    if set(g.objects(onto, OWL.versionIRI)) != {URIRef(f"{onto}/{version}")}:
        problems.append(f"owl:versionIRI tiene que ser {short(onto)}/{version}")
    if {str(v) for v in g.objects(onto, OWL.versionInfo)} != {version}:
        problems.append(f"owl:versionInfo tiene que ser «{version}», como el nombre del fichero")
    # Prefijo VANN = slug [PROPUESTA]: así lo hace el prototipo (itot, pqcm, didx).
    prefix_values = {str(v) for v in g.objects(onto, VANN.preferredNamespacePrefix)}
    if prefix_values != {slug}:
        problems.append(f"vann:preferredNamespacePrefix tiene que ser «{slug}», el slug de la ontología")
    for prefix in prefix_values:
        prefixes.setdefault(prefix, []).append(f"{rel(ONTO_DIR)}/{slug}/")

    # Cadena de versiones: la primera no tiene priorVersion y cada una de las
    # siguientes apunta a la inmediatamente anterior que hay en el repositorio.
    def key(v: str) -> tuple[int, ...]:
        return tuple(int(n) for n in v.split("."))

    siblings = sorted((p.stem for p in all_versions if p.parent == path.parent and SEMVER.match(p.stem)), key=key)
    earlier = [v for v in siblings if key(v) < key(version)]
    prior = set(g.objects(onto, OWL.priorVersion))
    expected_prior = {URIRef(f"{onto}/{earlier[-1]}")} if earlier else set()
    if prior != expected_prior:
        want = short(next(iter(expected_prior))) if expected_prior else "ninguna"
        problems.append(f"owl:priorVersion tiene que ser {want} (versión anterior en el repositorio)")
    for prop in (OWL.backwardCompatibleWith, OWL.incompatibleWith):
        for target in g.objects(onto, prop):
            if target not in {URIRef(f"{onto}/{v}") for v in earlier}:
                problems.append(f"{short(prop)} {short(target)} no es una versión anterior de esta ontología")

    # Marca de sintético y estado.
    for value in g.objects(onto, DCTERMS.type):
        if (value, RDF.type, SKOS.Concept) not in vocab:
            problems.append(f"dct:type {short(value)} no es un skos:Concept del vocabulario")
    if REQUIRE_SYNTHETIC_MARK and (onto, DCTERMS.type, URIRef(base + SYNTHETIC_TYPE)) not in g:
        problems.append(f"falta dct:type <{SYNTHETIC_TYPE}>")

    # dct:subject: conceptos SKOS existentes.
    for concept in g.objects(onto, DCTERMS.subject):
        if (concept, RDF.type, SKOS.Concept) not in vocab:
            problems.append(f"dct:subject {short(concept)} no es un skos:Concept de semantic/vocabularios/")

    # Términos propios en {URI}#; ningún otro recurso bajo BASE_URI.
    namespace = f"{onto}#"
    for subject in set(g.subjects()):
        if isinstance(subject, BNode) or not str(subject).startswith(base) or subject == onto:
            continue
        if not str(subject).startswith(namespace):
            problems.append(f"describe {short(subject)}, fuera del espacio de nombres {short(namespace)}")

    # owl:imports hacia ontologías externas catalogadas, y clases externas
    # (destinos de alineamiento) en el espacio de nombres de una de ellas.
    catalogued = set(external.subjects(RDF.type, OWL.Ontology))
    for target in g.objects(onto, OWL.imports):
        if target not in catalogued:
            problems.append(f"owl:imports {short(target)} no está en {rel(EXTERNAL_FILE)}")
    external_ns = [str(ns) for ns in external.objects(None, VANN.preferredNamespaceUri)]
    for cls in set(g.subjects(RDF.type, OWL.Class)):
        if isinstance(cls, URIRef) and not str(cls).startswith(namespace):
            if not any(str(cls).startswith(ns) for ns in external_ns):
                problems.append(f"la clase externa {short(cls)} no pertenece a ninguna ontología de {rel(EXTERNAL_FILE)}")
    for cls, parent in g.subject_objects(RDFS.subClassOf):
        if isinstance(parent, URIRef) and not str(parent).startswith(namespace) and (parent, RDF.type, OWL.Class) not in g:
            problems.append(f"{short(cls)} rdfs:subClassOf {short(parent)}: la clase externa no está declarada (owl:Class)")
    return problems


def external_coherence(g: Graph, base: str, prefixes: dict[str, list[str]]) -> list[str]:
    """externas.ttl: solo referencias, con la IRI oficial (fuera de BASE_URI)."""
    problems: list[str] = []
    short = short_of(base)
    ontologies = set(g.subjects(RDF.type, OWL.Ontology))
    if not ontologies:
        problems.append("no describe ninguna owl:Ontology")
    for onto in ontologies:
        if str(onto).startswith(base):
            problems.append(f"{short(onto)}: una ontología externa tiene la IRI oficial, fuera de BASE_URI")
        if g.value(onto, OWL.versionIRI) is not None:
            problems.append(f"{short(onto)}: una ontología externa no lleva owl:versionIRI (identifica las propias)")
        if g.value(onto, ADMS.status) is not None:
            problems.append(f"{short(onto)}: una ontología externa no lleva adms:status (su estado es «Referenciada»)")
        for prefix in g.objects(onto, VANN.preferredNamespacePrefix):
            prefixes.setdefault(str(prefix), []).append(f"{rel(EXTERNAL_FILE)} ({onto})")
    for subject in set(g.subjects()):
        if isinstance(subject, URIRef) and str(subject).startswith(base):
            problems.append(f"describe {short(subject)}, un recurso bajo BASE_URI")
    return problems


def coherence(g: Graph, base: str, synthetic: set[URIRef], vocab: Graph) -> list[str]:
    """Comprobaciones que no son SHACL porque cruzan datos y vocabulario.

    Son reglas de este repositorio sobre sus propios datos, no contrato de
    ingesta: el backend puede recibir versiones cuyos conceptos están en otro
    grafo.
    """
    problems: list[str] = []
    synthetic_type = URIRef(base + SYNTHETIC_TYPE)
    versions = set(g.subjects(RDF.type, DCAT.Dataset))
    series = set(g.subjects(RDF.type, DCAT.DatasetSeries))
    short = short_of(base)

    # Temas: conceptos de un esquema de dominio (con dct:subject hacia
    # vocab/dominio), y de un solo dominio por versión. «PQC e identidad»
    # tiene dos esquemas (pqc y did): lo que cuenta es el dominio, no el
    # esquema.
    for version in versions:
        found = set()
        for theme in g.objects(version, DCAT.theme):
            theme_domains = domain_of(vocab, base, theme)
            if (theme, RDF.type, SKOS.Concept) not in vocab or not theme_domains:
                problems.append(f"{short(version)}: el tema {short(theme)} no es un skos:Concept de un esquema de dominio")
            found |= theme_domains
        if len(found) > 1:
            problems.append(f"{short(version)}: temas de varios dominios ({', '.join(sorted(map(short, found)))})")

    # Marca de sintético en cada serie y versión de semantic/data/sintetico/,
    # y todo dct:type apunta a un concepto conocido.
    for subject in synthetic:
        if (subject, DCTERMS.type, synthetic_type) not in g:
            problems.append(f"{short(subject)}: falta dct:type <{SYNTHETIC_TYPE}>")
    for subject in versions | series:
        for value in g.objects(subject, DCTERMS.type):
            if (value, RDF.type, SKOS.Concept) not in g:
                problems.append(f"{short(subject)}: dct:type {short(value)} no es un skos:Concept del vocabulario")

    # Cada serie tiene dcat:last y sus extremos son versiones suyas.
    for serie in series:
        if g.value(serie, DCAT.last) is None:
            problems.append(f"{short(serie)}: falta dcat:last")
        for prop in (DCAT.first, DCAT.last):
            for target in g.objects(serie, prop):
                if (target, DCAT.inSeries, serie) not in g:
                    problems.append(f"{short(serie)}: {short(prop)} {short(target)} no es una versión de la serie")

    # Versiones: serie y versión anterior descritas, y URIs según uris.md.
    for version in versions:
        serie = g.value(version, DCAT.inSeries)
        if serie not in series:
            problems.append(f"{short(version)}: dcat:inSeries no apunta a una dcat:DatasetSeries descrita")
            continue
        number = g.value(version, DCAT.version)
        if str(version) != f"{serie}/{number}":
            problems.append(f"{short(version)}: la URI no es la de la serie seguida de /{number}")
        for previous in g.objects(version, DCAT.previousVersion):
            if (previous, DCAT.inSeries, serie) not in g:
                problems.append(f"{short(version)}: dcat:previousVersion {short(previous)} no es una versión descrita de la misma serie")
        for dist in g.objects(version, DCAT.distribution):
            if not str(dist).startswith(f"{version}/"):
                problems.append(f"{short(dist)}: la URI no cuelga de la de su versión")
            # Decisión del responsable (2026-11-14): accessURL = la propia URI.
            if set(g.objects(dist, DCAT.accessURL)) != {dist}:
                problems.append(f"{short(dist)}: dcat:accessURL tiene que ser la URI de la propia distribución")

    # Catálogo: cada dcat:dataset es una serie descrita, y están todas.
    for catalog in g.subjects(RDF.type, DCAT.Catalog):
        listed = set(g.objects(catalog, DCAT.dataset))
        for item in listed - series:
            problems.append(f"{short(catalog)}: dcat:dataset {short(item)} no es una dcat:DatasetSeries descrita")
        for item in series - listed:
            problems.append(f"{short(catalog)}: falta dcat:dataset {short(item)}")

    return sorted(problems)


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
