"""Pipeline de publicación de la fase 3 (agente ``qa``): revisión estática de
``.github/workflows/publicar.yml`` y pruebas de ``infra/scripts/publicar.py`` con etiquetas
hostiles.

No se empuja ninguna etiqueta ni se llama a GitHub: el script se ejecuta en local, contra
la carpeta ``semantic/`` real o contra un árbol de prueba (``REPO_ROOT``), y el workflow se
lee como texto. Se salta si ``infra/`` o ``.github/`` no están (imagen Docker del backend).

Está en ``backend/tests`` porque el script usa rdflib, que ya es dependencia del backend:
así se ejecuta en CI sin añadir nada.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from app.uris import SKOS
from tests.conftest import BASE_URI, REPO_SEMANTIC_DIR

REPO_ROOT = REPO_SEMANTIC_DIR.parent
PUBLICAR_PY = REPO_ROOT / "infra" / "scripts" / "publicar.py"
PUBLICAR_YML = REPO_ROOT / ".github" / "workflows" / "publicar.yml"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"no existe {path.relative_to(REPO_ROOT)} en este entorno")
    return path


# --- publicar.yml: revisión estática -----------------------------------------------------


@pytest.fixture(scope="module")
def workflow() -> str:
    return _require(PUBLICAR_YML).read_text(encoding="utf-8")


def _jobs(workflow: str) -> dict[str, str]:
    """Texto de cada job (``  nombre:`` bajo ``jobs:``)."""
    body = workflow.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][a-z0-9_-]*):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _run_blocks(workflow: str) -> list[str]:
    """Contenido de cada ``run:`` (de una línea o bloque ``|``)."""
    blocks: list[str] = []
    lines = workflow.splitlines()
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", lines[index])
        index += 1
        if not match:
            continue
        indent, rest = len(match.group(1)), match.group(2)
        if rest not in ("|", ">", "|-", ">-"):
            blocks.append(rest)
            continue
        block = []
        while index < len(lines) and (
            not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip()) > indent
        ):
            block.append(lines[index])
            index += 1
        blocks.append("\n".join(block))
    return blocks


def test_workflow_only_runs_on_version_tags(workflow: str) -> None:
    trigger = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.sub(r"\s+", " ", trigger).strip() == (
        'push: tags: - "onto/*/v*" - "vocab/*/v*" - "vocab/corp/*/v*"'
    )
    for event in (
        "pull_request",
        "pull_request_target",
        "workflow_dispatch",
        "schedule",
        "branches",
    ):
        assert event not in workflow, event


def test_workflow_permissions_are_minimal(workflow: str) -> None:
    # Por defecto, solo lectura.
    assert re.search(r"^permissions:\n  contents: read\n", workflow, re.MULTILINE)
    jobs = _jobs(workflow)
    assert set(jobs) == {"construir", "release"}
    granted = {
        name: re.findall(r"^\s+([a-z-]+): (write|read)$", text, re.MULTILINE)
        for name, text in jobs.items()
    }
    assert granted["construir"] == [("contents", "read")]
    assert granted["release"] == [("contents", "write")]
    assert workflow.count(": write") == 1
    for scope in ("id-token", "packages", "actions:", "pull-requests", "write-all"):
        assert scope not in workflow, scope
    # El job que ejecuta código del repositorio y el JAR de terceros no ve ningún secreto.
    assert "secrets." not in jobs["construir"]
    assert jobs["release"].count("secrets.") == 1
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in jobs["release"]
    # El job con permiso de escritura no hace checkout ni ejecuta código del repositorio.
    assert "actions/checkout" not in jobs["release"]
    assert "uv run" not in jobs["release"] and "java" not in jobs["release"]
    assert "needs: construir" in jobs["release"]


def test_workflow_actions_are_pinned_by_commit(workflow: str) -> None:
    uses = re.findall(r"uses:\s*(\S+)(.*)", workflow)
    assert len(uses) == 5
    for action, comment in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action), action
        assert re.search(r"#\s*v\d+\.\d+\.\d+", comment), (
            f"{action}: falta la versión en el comentario"
        )
    owners = {action.split("/")[0] for action, _ in uses}
    assert owners == {"actions", "astral-sh"}


def test_workflow_has_no_expression_inside_shell_code(workflow: str) -> None:
    """Las expresiones ``${{ … }}`` (etiqueta, salidas de pasos, variables) entran por
    ``env:`` y se usan entre comillas: nunca se interpolan en el texto de un ``run:``."""
    blocks = _run_blocks(workflow)
    assert len(blocks) >= 6
    for block in blocks:
        assert "${{" not in block, block
        assert "eval " not in block
        # Toda variable que viene de la etiqueta o de un paso se usa entre comillas dobles.
        for name in ("TAG", "NAME", "SOURCE", "KIND"):
            for use in re.finditer(rf"\$\{{?{name}\b\}}?", block):
                line = block[: use.end()].rsplit("\n", 1)[-1]
                assert line.count('"') % 2 == 1, f"${name} sin comillas: {line.strip()}"
    assert "TAG: ${{ github.ref_name }}" in workflow
    assert 'uv run infra/scripts/publicar.py --tag "$TAG" --out build' in workflow
    for forbidden in ("github.event.", "github.head_ref", "github.actor"):
        assert forbidden not in workflow, forbidden


def test_workflow_checks_the_tag_before_running_repository_code(workflow: str) -> None:
    build = _jobs(workflow)["construir"]
    ancestor = build.index('git merge-base --is-ancestor "$GITHUB_SHA" origin/main')
    assert "fetch-depth: 0" in build[:ancestor]
    for later in (
        "uv run semantic/scripts/validate.py",
        "uv run infra/scripts/publicar.py",
        "java -jar",
    ):
        assert ancestor < build.index(later), later
    assert build.index("validate.py") < build.index("publicar.py") < build.index("java -jar")


def test_workflow_verifies_the_tag_when_creating_the_release(workflow: str) -> None:
    release = _jobs(workflow)["release"]
    command = release[release.index("gh release create") :]
    assert '"$TAG"' in command and "--verify-tag" in command
    assert '--repo "$GITHUB_REPOSITORY"' in command
    assert "--notes-file build/notas.md" in command
    for risky in ("--draft=false", "--generate-notes", "--target", "--latest"):
        assert risky not in command, risky


def test_widoco_jar_is_pinned_and_verified_by_sha256(workflow: str) -> None:
    version = re.search(r'WIDOCO_VERSION: "(\d+\.\d+\.\d+)"', workflow)
    digest = re.search(r'WIDOCO_SHA256: "([0-9a-f]{64})"', workflow)
    assert version and digest
    step = workflow[workflow.index("- name: Documentación con WIDOCO") :]
    step = step[: step.index("- name: Empaquetar")]
    download = step.index("curl -fsSL -o widoco.jar")
    check = step.index('echo "${WIDOCO_SHA256}  widoco.jar" | sha256sum -c -')
    execute = step.index("java -jar")
    assert download < check < execute
    assert '"https://github.com/dgarijo/Widoco/releases/download/v${WIDOCO_VERSION}/${jar}"' in step
    assert step.count("curl ") == 1 and "wget" not in workflow
    assert "--insecure" not in workflow and " -k " not in workflow
    # El bloque se ejecuta con `bash -e` (por defecto en Actions): si la suma no coincide,
    # no se llega a ejecutar el JAR. Nada desactiva ese comportamiento.
    assert "set +e" not in workflow and "|| true" not in workflow
    assert "continue-on-error" not in workflow


def test_workflow_has_timeouts_and_does_not_cancel_a_release(workflow: str) -> None:
    for name, text in _jobs(workflow).items():
        assert re.search(r"timeout-minutes: \d+", text), name
        assert "runs-on: ubuntu-24.04" in text, name
    assert "cancel-in-progress: false" in workflow
    assert "group: publicar-${{ github.ref }}" in workflow


# --- publicar.py: etiquetas hostiles ------------------------------------------------------


def _run(
    tag: str, out: Path, *, root: Path | None = None, extra_env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Ejecuta ``publicar.py`` como lo hace el workflow. Devuelve también el fichero que
    hace de ``GITHUB_OUTPUT``."""
    github_output = out.parent / f"{out.name}.github_output"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "BASE_URI": BASE_URI,
        "GITHUB_OUTPUT": str(github_output),
        **(extra_env or {}),
    }
    if root is not None:
        env["REPO_ROOT"] = str(root)
    result = subprocess.run(  # noqa: S603 - intérprete y script del repositorio, sin shell
        [sys.executable, str(_require(PUBLICAR_PY)), "--tag", tag, "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
        cwd=out.parent,
    )
    return result, github_output


HOSTILE_TAGS = [
    # Rutas.
    "onto/../../etc/passwd/v1.0.0",
    "onto/itot/v../../1.2.0",
    "onto/itot/../pqcm/v0.4.0",
    "onto/./itot/v1.2.0",
    "onto//v1.2.0",
    "onto/itot//v1.2.0",
    "/onto/itot/v1.2.0",
    "onto/itot/v1.2.0/",
    "onto/itot/v1.2.0/../../../x",
    "vocab/corp/../ot/v1.0",
    "vocab/..%2f..%2fetc/v1.0",
    "onto\\itot\\v1.2.0",
    "refs/tags/onto/itot/v1.2.0",
    # Inyección en el shell o en GITHUB_OUTPUT.
    "onto/itot/v1.2.0; touch pwned",
    "onto/itot/v1.2.0 && touch pwned",
    "onto/$(touch pwned)/v1.2.0",
    "onto/`touch pwned`/v1.2.0",
    "onto/itot/v1.2.0|touch pwned",
    "onto/itot/v1.2.0\nkind=vocab",
    "onto/itot/v1.2.0\r\nname=../../x",
    "onto/itot\nname=x/v1.2.0",
    "--out=/tmp/x",
    "-h",
    # Fuera del patrón.
    "",
    "onto",
    "onto/itot",
    "onto/itot/1.2.0",
    "onto/itot/V1.2.0",
    "onto/ITOT/v1.2.0",
    "onto/itot/v1.2",
    "onto/itot/v01.2.0",
    "onto/itot/v1.2.0-rc.1",
    "onto/itot/v1.2.0.0",
    "onto/ito_t/v1.2.0",
    "onto/-itot/v1.2.0",
    "vocab/ot/v1",
    "vocab/ot/v1.0.0.0",
    "vocab/ot/vlatest",
    "vocab/corp/trl/extra/v1.0",
    "dataset/modbus-tcp-testbed/v2.1.0",
    "shapes/v1.0",
    "ónto/itot/v1.2.0",
    "onto/itot/v١.٢.٠",  # noqa: RUF001 - dígitos no ASCII
    # Slugs reservados y ficheros que no son de una versión.
    "onto/externas/v1.0.0",
    "vocab/corp/v1.0",
    "vocab/dominio/v1.0",
    "vocab/tipo-dataset/v1.0",
    # Versión que no es la del fichero.
    "onto/itot/v9.9.9",
    "onto/itot/v1.2.1",
    "vocab/ot/v9.9",
    "vocab/ot/v1.0.0",
    "vocab/corp/trl/v2026.1",
    "vocab/trl/v1.0",  # corporativo pedido como de dominio
    "vocab/corp/ot/v1.0",  # de dominio pedido como corporativo
]


@pytest.mark.parametrize("tag", HOSTILE_TAGS)
def test_hostile_or_wrong_tags_fail_without_writing_anything(tag: str, tmp_path: Path) -> None:
    work = tmp_path / "trabajo"
    work.mkdir()
    out = work / "build"
    result, github_output = _run(tag, out)
    assert result.returncode != 0, f"{tag!r} se ha aceptado:\n{result.stdout}"
    assert "Traceback" not in result.stderr, result.stderr
    assert not github_output.exists(), "se ha escrito GITHUB_OUTPUT para una etiqueta rechazada"
    # Nada escrito: ni artefactos, ni ficheros fuera de la carpeta de salida.
    assert not out.exists() or list(out.rglob("*")) == []
    assert sorted(p.name for p in tmp_path.rglob("*")) == ["trabajo"] + (
        ["build"] if out.exists() else []
    )
    assert not (work / "pwned").exists() and not (REPO_ROOT / "pwned").exists()


@pytest.mark.xfail(
    strict=True,
    reason="QA-G3-08: publicar.py valida la etiqueta con re.match y '$', que admite un salto "
    "de línea final ('onto/itot/v1.2.0\\n'); debería usar fullmatch. Git no permite crear esa "
    "etiqueta y los nombres de salida no cambian, así que es solo defensa en profundidad",
)
def test_tag_with_trailing_newline_is_rejected(tmp_path: Path) -> None:
    result, github_output = _run("onto/itot/v1.2.0\n", tmp_path / "build")
    assert result.returncode != 0
    assert not github_output.exists()


VALID_TAGS = [
    ("onto/itot/v1.2.0", "onto", "itot", "1.2.0", "semantic/ontologias/itot/1.2.0.ttl"),
    ("onto/itot/v1.0.0", "onto", "itot", "1.0.0", "semantic/ontologias/itot/1.0.0.ttl"),
    ("onto/pqcm/v0.4.0", "onto", "pqcm", "0.4.0", "semantic/ontologias/pqcm/0.4.0.ttl"),
    ("vocab/ot/v1.0", "vocab", "ot", "1.0", "semantic/vocabularios/ot.ttl"),
    ("vocab/it/v1.1", "vocab", "it", "1.1", "semantic/vocabularios/it.ttl"),
    ("vocab/corp/trl/v1.0", "vocab-corp", "trl", "1.0", "semantic/vocabularios/corp/trl.ttl"),
    (
        "vocab/corp/financiacion/v2026.1",
        "vocab-corp",
        "financiacion",
        "2026.1",
        "semantic/vocabularios/corp/financiacion.ttl",
    ),
]


@pytest.mark.parametrize(("tag", "kind", "slug", "version", "source"), VALID_TAGS)
def test_valid_tag_writes_only_safe_artifacts(
    tag: str, kind: str, slug: str, version: str, source: str, tmp_path: Path
) -> None:
    _require(REPO_ROOT / source)
    out = tmp_path / "build"
    result, github_output = _run(tag, out)
    assert result.returncode == 0, result.stderr
    name = tag.rsplit("/v", 1)[0].replace("/", "-") + "-" + version
    expected = {f"{name}.ttl", f"{name}.jsonld"}
    expected |= {f"{name}.rdf"} if kind == "onto" else {"docs", "docs/index.html"}
    assert {p.relative_to(out).as_posix() for p in out.rglob("*")} == expected
    for path in out.rglob("*"):
        assert re.fullmatch(r"[a-z0-9.-]+", path.name), path.name
    # GITHUB_OUTPUT: cinco líneas clave=valor, sin nada que venga del contenido del RDF.
    assert github_output.read_text(encoding="utf-8").splitlines() == [
        f"kind={kind}",
        f"slug={slug}",
        f"version={version}",
        f"name={name}",
        f"source={source}",
    ]
    # Las IRIs relativas se han expandido con BASE_URI y el RDF es el del fichero.
    original = Graph().parse(REPO_ROOT / source, format="turtle", publicID=BASE_URI)
    published = Graph().parse(out / f"{name}.ttl", format="turtle")
    assert len(published) == len(original)
    subjects = {str(s) for s in published.subjects() if isinstance(s, URIRef)}
    assert subjects and all(s.startswith(("http://", "https://")) for s in subjects)
    root_type = OWL.Ontology if kind == "onto" else SKOS.ConceptScheme
    (resource,) = set(published.subjects(RDF.type, root_type))
    assert str(resource).startswith(BASE_URI)
    assert str(published.value(resource, OWL.versionInfo)) == version


def test_base_uri_comes_from_the_environment(tmp_path: Path) -> None:
    out = tmp_path / "build"
    result, _ = _run("vocab/ot/v1.0", out, extra_env={"BASE_URI": "https://otra.example/base"})
    assert result.returncode == 0, result.stderr
    graph = Graph().parse(out / "vocab-ot-1.0.ttl", format="turtle")
    (scheme,) = set(graph.subjects(RDF.type, SKOS.ConceptScheme))
    assert str(scheme) == "https://otra.example/base/vocab/ot"
    assert BASE_URI not in (out / "vocab-ot-1.0.ttl").read_text(encoding="utf-8")


def _fake_tree(root: Path, relative: str, body: str) -> Path:
    path = root / "semantic" / relative
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    return root


HOSTILE_TEXT = "</td><script>alert(1)</script><img src=x onerror=alert(2)>\"'"
HOSTILE_SCHEME = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<vocab/prueba> a skos:ConceptScheme ; owl:versionInfo "1.0" ;
    skos:prefLabel '''{HOSTILE_TEXT}'''@es .
<vocab/prueba/c> a skos:Concept ; skos:inScheme <vocab/prueba> ;
    skos:prefLabel '''{HOSTILE_TEXT}'''@es ; skos:definition '''{HOSTILE_TEXT}
kind=onto
name=../../x'''@es ;
    skos:broader <vocab/prueba/d> .
<vocab/prueba/d> a skos:Concept ; skos:inScheme <vocab/prueba> ;
    skos:prefLabel '''{HOSTILE_TEXT}'''@es .
<javascript:alert(1)> a skos:Concept ; skos:inScheme <vocab/prueba> ;
    skos:prefLabel "js"@es .
"""


def test_html_page_escapes_the_rdf_content(tmp_path: Path) -> None:
    root = _fake_tree(tmp_path / "repo", "vocabularios/prueba.ttl", HOSTILE_SCHEME)
    out = tmp_path / "build"
    result, github_output = _run("vocab/prueba/v1.0", out, root=root)
    assert result.returncode == 0, result.stderr
    page = (out / "docs" / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in page and "<img" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert (
        re.findall(
            r"<(?!/?(?:!doctype|html|head|meta|title|body|h1|p|table|thead|tbody|tr|th|td|a)\b)",
            page,
        )
        == []
    )
    # Ningún atributo se cierra con el contenido.
    for href in re.findall(r'href="([^"]*)"', page):
        assert "<" not in href and ">" not in href
    # El contenido del RDF no añade líneas a GITHUB_OUTPUT.
    lines = github_output.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "kind=vocab",
        "slug=prueba",
        "version=1.0",
        "name=vocab-prueba-1.0",
        "source=semantic/vocabularios/prueba.ttl",
    ]


@pytest.mark.parametrize(
    ("relative", "tag", "body"),
    [
        # Dos ontologías en el fichero.
        (
            "ontologias/x/1.0.0.ttl",
            "onto/x/v1.0.0",
            "@prefix owl: <http://www.w3.org/2002/07/owl#> . <onto/x> a owl:Ontology ; "
            'owl:versionInfo "1.0.0" . <onto/y> a owl:Ontology ; owl:versionInfo "1.0.0" .',
        ),
        # Sin versión.
        (
            "ontologias/x/1.0.0.ttl",
            "onto/x/v1.0.0",
            "@prefix owl: <http://www.w3.org/2002/07/owl#> . <onto/x> a owl:Ontology .",
        ),
        # versionIRI de otra versión.
        (
            "ontologias/x/1.0.0.ttl",
            "onto/x/v1.0.0",
            "@prefix owl: <http://www.w3.org/2002/07/owl#> . <onto/x> a owl:Ontology ; "
            'owl:versionInfo "1.0.0" ; owl:versionIRI <onto/x/2.0.0> .',
        ),
        # Esquema sin versión y fichero sin esquema.
        (
            "vocabularios/x.ttl",
            "vocab/x/v1.0",
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> . "
            "<vocab/x> a skos:ConceptScheme .",
        ),
        (
            "vocabularios/x.ttl",
            "vocab/x/v1.0",
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> . <vocab/x/c> a skos:Concept .",
        ),
    ],
)
def test_file_that_does_not_match_the_tag_is_not_published(
    relative: str, tag: str, body: str, tmp_path: Path
) -> None:
    root = _fake_tree(tmp_path / "repo", relative, body)
    out = tmp_path / "build"
    result, github_output = _run(tag, out, root=root)
    assert result.returncode == 1, result.stdout
    assert result.stderr.startswith("ERROR: ")
    assert not github_output.exists()
    assert not out.exists() or list(out.rglob("*")) == []


def test_symlinked_source_outside_the_repository_is_not_followed_silently(tmp_path: Path) -> None:
    """Un fichero de versión que es un enlace simbólico a algo que no es RDF falla al
    analizarlo y no publica nada."""
    secret = tmp_path / "secreto.txt"
    secret.write_text("root:x:0:0:no es turtle\n", encoding="utf-8")
    root = tmp_path / "repo"
    target = root / "semantic" / "ontologias" / "x"
    target.mkdir(parents=True)
    (target / "1.0.0.ttl").symlink_to(secret)
    out = tmp_path / "build"
    result, github_output = _run("onto/x/v1.0.0", out, root=root)
    assert result.returncode != 0
    assert "root:x:0:0" not in result.stdout
    assert not github_output.exists()
    assert not out.exists() or list(out.rglob("*")) == []
