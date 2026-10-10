"""
Cliente y operaciones de Git y GitHub CLI.
Responsabilidad única: Gestión de repositorios, branches, commits, diffs y PRs.
"""

from pathlib import Path
from pilot.config import LOGS_DIR, get_logs_dir
from pilot.core.shell import run_command, run_command_args
from pilot.core.ui import warn

class GitClient:
    def __init__(self, repo_path: str):
        self.repo = str(Path(repo_path).resolve())

    def run(self, cmd: str) -> tuple[int, str, str]:
        return run_command(f"git {cmd}", cwd=self.repo)

    def is_valid_repo(self) -> bool:
        code, _, _ = self.run("rev-parse --git-dir")
        return code == 0

    def current_branch(self) -> str:
        _, out, _ = self.run("rev-parse --abbrev-ref HEAD")
        return out.strip() or "HEAD"

    def create_branch(self, branch: str) -> bool:
        code, _, _ = self.run(f"checkout -b {branch}")
        if code != 0:
            code2, _, _ = self.run(f"checkout {branch}")
            return code2 == 0
        return True

    def commit(self, message: str) -> bool:
        """Hace git add -A y commit. Retorna False si no había cambios preparados."""
        self.run("add -A")
        _, status, _ = self.run("diff --cached --stat")
        if not status.strip():
            warn("El agente no modificó archivos — commit omitido (sin cambios staged).")
            return False
        code, _, commit_err = run_command_args(["git", "commit", "--no-verify", "-m", message], cwd=self.repo)
        if code != 0:
            warn(f"git commit falló: {commit_err[:100]}")
        return code == 0

    def diff_vs_base(self, base: str = "main") -> str:
        """Calcula el diff frente a la rama base con fallbacks."""
        for ref in [f"{base}...HEAD", f"origin/{base}...HEAD"]:
            _, diff, _ = self.run(f"diff {ref}")
            if diff.strip():
                return diff
        _, diff, _ = self.run("diff HEAD~1 HEAD")
        return diff or "(sin cambios detectados)"

    def changed_files(self, base: str = "main") -> list[str]:
        """Lista archivos modificados contra la base."""
        for ref in [f"{base}...HEAD", f"origin/{base}...HEAD"]:
            _, out, _ = self.run(f"diff --name-only {ref}")
            files = [f.strip() for f in out.splitlines() if f.strip()]
            if files:
                return files
        return []

    def push_and_create_pr(self, branch: str, title: str, body: str) -> str:
        """Hace push y abre una Draft PR con GitHub CLI."""
        self.run(f"push -u origin {branch}")
        logs_dir = get_logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        body_file = logs_dir / "_pr_body.md"
        body_file.write_text(body, encoding="utf-8")
        code, out, err_msg = run_command_args(
            ["gh", "pr", "create", "--draft", "--title", title, "--body-file", str(body_file)],
            cwd=self.repo
        )
        body_file.unlink(missing_ok=True)
        if code == 0:
            return out.strip()
        warn(f"gh pr create falló: {err_msg[:200]}")
        return f"(PR no creada — error: {err_msg[:100]})"

    def get_remote_origin(self) -> str | None:
        code, out, _ = self.run("remote get-url origin")
        return out.strip() if code == 0 else None
