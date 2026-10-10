"""
Motor de revisión de ramas (review).
Responsabilidad única: Auditar los cambios de la rama git actual frente a una rama base.
"""

from pilot.core.git import GitClient
from pilot.core.runner import AgentRunner, default_runner
from pilot.core.ui import Colors, banner, info, ok, warn
from pilot.engines.pipeline import phase_review

def audit_branch(
    repo: str,
    base_branch: str = "main",
    ticket: str = "",
    runner: AgentRunner | None = None,
) -> dict:
    banner(f"AUDITORÍA DE RAMA — vs {base_branch}", Colors.CYAN)
    active_runner = runner or default_runner
    git_client = GitClient(repo)

    current = git_client.current_branch()
    info(f"Rama actual: {current}")

    files = git_client.changed_files(base_branch)
    if not files:
        warn(f"No se detectaron archivos modificados respecto a '{base_branch}'.")
        info("Asegúrate de haber hecho commits o usa --base para indicar la rama correcta.")
        return {}

    ok(f"Archivos modificados ({len(files)}):")
    for f in files:
        info(f"  • {f}")

    ticket_desc = ticket or f"Code review de cambios en {current}"
    return phase_review(ticket_desc, current, repo, base_branch, active_runner, git_client)
