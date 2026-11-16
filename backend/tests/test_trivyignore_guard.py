"""Guarda de ``.trivyignore.yaml`` (propuesta de ``qa`` en la PR #24).

La excepción de Trivy para la JRE de Pellet no puede crecer ni volverse permanente sin que
una prueba falle:

- Una sola excepción, de ``vulnerabilities``, con ``id`` (CVE), ``statement`` y ``expired_at``.
- ``expired_at`` es una fecha futura y a 6 meses como máximo desde hoy.
- Nada de ``paths`` (alcance amplio) ni de otras secciones (``misconfigurations``, ``secrets``,
  ``licenses``).
- El job de Trivy de ``ci.yml`` mantiene la severidad (``CRITICAL``) y ``exit-code: "1"``, usa
  ese fichero y no oculta lo que no tiene corrección (``ignore-unfixed``).

PyYAML no es dependencia directa del backend: llega como dependencia de
``uvicorn[standard]`` (``uv.lock``) y por eso está instalado. Si algún día dejara de estar,
las pruebas se saltan en lugar de fallar. El fichero real aún puede no existir en la rama:
entonces su prueba se salta; la lógica se prueba siempre con casos sintéticos.
"""

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import REPO_SEMANTIC_DIR

yaml = pytest.importorskip("yaml")

REPO_ROOT = REPO_SEMANTIC_DIR.parent
TRIVYIGNORE = REPO_ROOT / ".trivyignore.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAX_DAYS = 183  # 6 meses
CVE = re.compile(r"CVE-\d{4}-\d{4,}")
ALLOWED_KEYS = {"id", "statement", "expired_at", "purls"}


def check_trivyignore(document: Any, today: date) -> list[str]:
    """Problemas de un ``.trivyignore.yaml`` ya leído (lista vacía si cumple la guarda)."""
    problems: list[str] = []
    if not isinstance(document, dict):
        return ["el fichero no es un mapa YAML"]
    extra = set(document) - {"vulnerabilities"}
    if extra:
        problems.append(f"secciones no permitidas: {sorted(extra)}")
    entries = document.get("vulnerabilities")
    if not isinstance(entries, list) or len(entries) != 1:
        count = len(entries) if isinstance(entries, list) else 0
        return [*problems, f"debe haber exactamente 1 excepción, hay {count}"]
    entry = entries[0]
    if not isinstance(entry, dict):
        return [*problems, "la excepción no es un mapa"]
    if set(entry) - ALLOWED_KEYS:
        problems.append(f"claves no permitidas: {sorted(set(entry) - ALLOWED_KEYS)}")
    if not isinstance(entry.get("id"), str) or not CVE.fullmatch(entry["id"]):
        problems.append("id debe ser un CVE concreto (sin comodines)")
    statement = entry.get("statement")
    if not isinstance(statement, str) or len(statement.strip()) < 10:
        problems.append("falta un statement que justifique la excepción")
    expired = entry.get("expired_at")
    if isinstance(expired, str):  # Trivy también acepta la fecha entre comillas
        try:
            expired = date.fromisoformat(expired)
        except ValueError:
            expired = None
    if not isinstance(expired, date):
        problems.append("expired_at debe ser una fecha AAAA-MM-DD")
    else:
        if expired <= today:
            problems.append(f"expired_at ({expired}) ya ha pasado o es hoy")
        if expired > today + timedelta(days=MAX_DAYS):
            problems.append(f"expired_at ({expired}) está a más de 6 meses")
    return problems


def test_the_real_trivyignore_meets_the_guard() -> None:
    if not TRIVYIGNORE.exists():
        pytest.skip(".trivyignore.yaml aún no existe en esta rama (PR #24)")
    document = yaml.safe_load(TRIVYIGNORE.read_text(encoding="utf-8"))
    assert check_trivyignore(document, date.today()) == []


def test_the_real_trivyignore_has_no_secrets_or_internal_links() -> None:
    if not TRIVYIGNORE.exists():
        pytest.skip(".trivyignore.yaml aún no existe en esta rama (PR #24)")
    text = TRIVYIGNORE.read_text(encoding="utf-8")
    assert "claude.ai" not in text and "@" not in text.replace("@@", "")


def check_trivy_step(step: dict[str, Any], *, ignore_file: bool = True) -> list[str]:
    """Problemas del paso de Trivy de ``ci.yml`` (lista vacía si cumple la guarda)."""
    options = step.get("with") or {}
    problems = []
    if options.get("severity") != "CRITICAL":
        problems.append("severity debe seguir siendo CRITICAL")
    if str(options.get("exit-code")) != "1":
        problems.append('exit-code debe seguir siendo "1"')
    if ignore_file and options.get("trivyignores") != ".trivyignore.yaml":
        problems.append("trivyignores debe apuntar a .trivyignore.yaml")
    if str(options.get("ignore-unfixed", "false")).lower() != "false":
        problems.append("ignore-unfixed ocultaría lo que no tiene corrección")
    if step.get("continue-on-error"):
        problems.append("el escaneo no puede dejar de ser bloqueante")
    if not re.search(r"@[0-9a-f]{40}\b", str(step.get("uses", ""))):
        problems.append("la acción debe ir fijada por commit")
    return problems


def _trivy_step() -> dict[str, Any]:
    if not CI_WORKFLOW.exists():
        pytest.skip("no existe .github/workflows/ci.yml en este entorno")
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("aquasecurity/trivy-action@"):
                return step
    pytest.skip("ci.yml aún no tiene el job de Trivy (PR #24)")


def test_ci_keeps_severity_exit_code_and_the_ignore_file() -> None:
    # Mientras .trivyignore.yaml no exista (PR #24), solo se exige lo demás: severidad,
    # exit-code, sin ignore-unfixed y acción fijada. Con el fichero, el paso debe usarlo.
    assert check_trivy_step(_trivy_step(), ignore_file=TRIVYIGNORE.exists()) == []


# --- La guarda detecta lo que debe (casos sintéticos) ------------------------------------

TODAY = date(2026, 11, 16)
GOOD = """
vulnerabilities:
  - id: CVE-2026-114820
    statement: "JRE solo para Pellet, sin red, sin corrección"
    expired_at: 2027-02-15
"""


def _problems(text: str, today: date = TODAY) -> list[str]:
    return check_trivyignore(yaml.safe_load(text), today)


def test_guard_accepts_the_expected_shape() -> None:
    assert _problems(GOOD) == []
    assert _problems(GOOD.replace("2027-02-15", '"2027-02-15"')) == []
    assert _problems(GOOD.replace("2027-02-15", "2027-05-17")) == []  # ≤ 6 meses


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda t: t.replace("2027-02-15", "2026-11-16"), "ya ha pasado"),
        (lambda t: t.replace("2027-02-15", "2026-01-01"), "ya ha pasado"),
        (lambda t: t.replace("2027-02-15", "2027-06-01"), "más de 6 meses"),
        (lambda t: t.replace("2027-02-15", "2099-01-01"), "más de 6 meses"),
        (lambda t: t.replace("    expired_at: 2027-02-15\n", ""), "expired_at"),
        (lambda t: t.replace("2027-02-15", "pronto"), "expired_at"),
        (
            lambda t: t.replace(
                '    statement: "JRE solo para Pellet, sin red, sin corrección"\n', ""
            ),
            "statement",
        ),
        (
            lambda t: t.replace(
                'statement: "JRE solo para Pellet, sin red, sin corrección"', 'statement: ""'
            ),
            "statement",
        ),
        (lambda t: t.replace("CVE-2026-114820", "CVE-*"), "CVE"),
        (lambda t: t.replace("CVE-2026-114820", "GHSA-xxxx"), "CVE"),
        (lambda t: t + "    paths:\n      - '**'\n", "no permitidas"),
        (lambda t: t + "misconfigurations:\n  - id: AVD-DS-0002\n", "secciones no permitidas"),
        (lambda t: t + "secrets:\n  - id: aws-access-key-id\n", "secciones no permitidas"),
        (
            lambda t: (
                t
                + "  - id: CVE-2026-1\n    statement: otra cosa larga\n    expired_at: 2027-01-01\n"
            ),
            "exactamente 1",
        ),
        (lambda t: "vulnerabilities: []\n", "exactamente 1"),
        (lambda t: "- id: CVE-2026-114820\n", "mapa"),
    ],
)
def test_guard_rejects_what_widens_or_perpetuates_the_exception(mutation, expected: str) -> None:
    problems = _problems(mutation(GOOD))
    assert problems, "la guarda debería haber fallado"
    assert any(expected in p for p in problems), problems


GOOD_STEP = """
uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25
with:
  severity: CRITICAL
  exit-code: "1"
  trivyignores: .trivyignore.yaml
"""


def test_step_guard_accepts_the_expected_step() -> None:
    assert check_trivy_step(yaml.safe_load(GOOD_STEP)) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("severity: CRITICAL", "severity: HIGH,CRITICAL", "severity"),
        ("severity: CRITICAL", "severity: CRITICAL,LOW", "severity"),
        ('exit-code: "1"', 'exit-code: "0"', "exit-code"),
        ("trivyignores: .trivyignore.yaml", "trivyignores: otro.yaml", "trivyignores"),
        ("  exit-code", "  ignore-unfixed: true\n  exit-code", "ignore-unfixed"),
        ("with:", "continue-on-error: true\nwith:", "bloqueante"),
        ("@ed142fd0673e97e23eac54620cfb913e5ce36c25", "@v0.36.0", "fijada"),
    ],
)
def test_step_guard_rejects_a_weakened_scan(old: str, new: str, expected: str) -> None:
    assert old in GOOD_STEP
    problems = check_trivy_step(yaml.safe_load(GOOD_STEP.replace(old, new)))
    assert any(expected in p for p in problems), problems


def test_repo_root_is_resolved() -> None:
    assert isinstance(REPO_ROOT, Path) and (REPO_ROOT / "CLAUDE.md").exists()
