"""
Abstracción para la ejecución de agentes de Inteligencia Artificial.
Cumple Principio de Inversión de Dependencias (D): los motores dependen de esta abstracción
y no de la invocación directa a bajo nivel de agy o subprocess.
"""

import subprocess
import time
from typing import Protocol

from pilot.config import (
    LOGS_DIR,
    MAX_ARGV_PROMPT,
    get_default_effort,
    get_default_model,
)
from pilot.core.ui import err, warn

class AgentRunner(Protocol):
    """Protocolo/Interfaz para cualquier proveedor de ejecución de agentes."""
    def run(self, prompt: str, repo_path: str, new_project: bool = True, model: str | None = None) -> tuple[int, str]:
        ...

class AgyRunner:
    """Implementación concreta que invoca la CLI de agy no interactiva."""
    def __init__(self, default_model: str | None = None, effort: str | None = None):
        self.default_model = default_model or get_default_model()
        self.effort = effort or get_default_effort()

    def run(self, prompt: str, repo_path: str, new_project: bool = True, model: str | None = None) -> tuple[int, str]:
        ts = int(time.time())
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOGS_DIR / f"_agy_raw_{ts}.log"

        effective_model = model if model else self.default_model

        base_args = [
            "agy",
            "--model", effective_model,
            "--add-dir", repo_path,
            "--disable-slash-commands",
            "--dangerously-skip-permissions",
            "--mode", "accept-edits",
        ]
        if self.effort:
            base_args.extend(["--effort", self.effort])
        if new_project:
            base_args.append("--new-project")

        # Proteger argv de overflow en el SO
        if len(prompt) > MAX_ARGV_PROMPT:
            warn(f"Prompt extenso ({len(prompt)} caracteres) recortado a {MAX_ARGV_PROMPT} para ejecución.")
            prompt = prompt[:MAX_ARGV_PROMPT] + "\n...[CONTEXTO TRUNCADO POR SEGURIDAD]..."

        cmd_args = base_args + ["--print", prompt]

        try:
            result = subprocess.run(
                cmd_args,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=360,
            )
        except subprocess.TimeoutExpired:
            warn(f"agy tardó más de 6 minutos — posible cuelgue. Log: {log_file.name}")
            log_file.write_text("=== TIMEOUT ===\n", encoding="utf-8")
            return 1, ""
        except FileNotFoundError:
            err("Comando 'agy' no encontrado. Verifica que esté en el PATH.")
            return 1, ""

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        log_file.write_text(
            f"=== EXIT CODE: {result.returncode} ===\n"
            f"=== PROMPT LENGTH: {len(prompt)} chars ===\n"
            f"=== STDOUT ===\n{stdout}\n"
            f"=== STDERR ===\n{stderr}\n",
            encoding="utf-8"
        )

        if result.returncode != 0 and not stdout:
            noisy = {"ERROR: logging", "read-only file system", "stack trace",
                     "Wraps:", "Error types:", "--  stack trace:"}
            useful = [l for l in stderr.splitlines()
                      if l.strip() and not any(n in l for n in noisy)]
            if useful:
                warn(f"agy stderr: {useful[0][:150]}")

        return result.returncode, stdout

# Runner por defecto instanciable
default_runner = AgyRunner()

def run_agy(prompt: str, repo_path: str, new_project: bool = True, model_override: str | None = None) -> tuple[int, str]:
    """Helper global para compatibilidad con llamadas existentes."""
    return default_runner.run(prompt, repo_path, new_project=new_project, model=model_override)
