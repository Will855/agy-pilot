"""
Motor de diagnóstico del entorno (Doctor).
Responsabilidad única: Validación integral del sistema antes de comenzar una sesión.
"""

import sys
from shutil import which

from pilot.config import LOGS_DIR
from pilot.core.git import GitClient
from pilot.core.runner import AgentRunner, AgyRunner
from pilot.core.ui import Colors, banner, err, info, ok, warn

def run_doctor(repo: str, runner: AgentRunner | None = None) -> bool:
    """Verifica que el entorno esté listo para ejecutar pipelines."""
    banner("DIAGNÓSTICO DEL ENTORNO (doctor)", Colors.CYAN)
    all_ok = True
    active_runner = runner or AgyRunner()

    checks = [
        ("agy disponible", lambda: which("agy") is not None),
        ("git disponible", lambda: which("git") is not None),
        ("gh disponible (para PRs)", lambda: which("gh") is not None),
        ("directorio de logs escribible", lambda: _check_logs_writable()),
        ("python3 >= 3.10", lambda: sys.version_info >= (3, 10)),
    ]

    for name, check_fn in checks:
        try:
            passed = check_fn()
        except Exception:
            passed = False
        if passed:
            ok(name)
        else:
            err(name)
            all_ok = False

    # Prueba real de agy con prompt mínimo
    info("Probando agy --print con prompt de prueba...")
    test_repo = repo if repo else "."
    code, output = active_runner.run("Responde solo la palabra PILOTOK", test_repo, new_project=True)
    if code == 0 and output.strip():
        ok(f"agy responde correctamente (output: '{output[:40].strip()}')")
    else:
        err(f"agy no respondió (exit={code}, output='{output[:40]}')")
        err("  Revisa que 'agy' esté autenticado y funcionando en tu terminal.")
        all_ok = False

    # Verificar git remoto
    if repo:
        git_client = GitClient(repo)
        remote = git_client.get_remote_origin()
        if remote:
            ok(f"Git remote: {remote[:60]}")
        else:
            warn("Sin remote 'origin' — las PRs automáticas no funcionarán.")

    print()
    if all_ok:
        ok("Entorno listo ✓ — puedes ejecutar el pipeline")
    else:
        err("Hay problemas en el entorno. Corrígelos antes de ejecutar run/review/audit.")
    return all_ok

def _check_logs_writable() -> bool:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    t = LOGS_DIR / ".doctor_write_test"
    try:
        t.write_text("ok")
        t.unlink()
        return True
    except OSError:
        return False
