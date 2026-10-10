"""
Gestor de persistencia de logs y lectura de plantillas de prompts.
Responsabilidad única: Entrada/Salida de archivos (logs y templates).
"""

import sys
from datetime import datetime
from pathlib import Path
from shutil import which

from pilot.config import AGENTS_DIR, DEFAULT_LOGS_DIR, get_logs_dir
from pilot.core.ui import err, info, warn

def check_system_prerequisites() -> None:
    """Valida que las herramientas indispensables y el directorio de logs estén disponibles."""
    missing = []
    for tool in ["agy", "git"]:
        if not which(tool):
            missing.append(tool)
    if missing:
        err(f"Herramientas faltantes: {', '.join(missing)}")
        err("Instálalas antes de continuar.")
        sys.exit(1)

    active_logs = get_logs_dir()
    import os
    if active_logs != DEFAULT_LOGS_DIR and not os.environ.get("PILOT_LOGS_DIR"):
        warn(f"Directorio predeterminado de logs ({DEFAULT_LOGS_DIR}) no es escribible. Usando fallback seguro: {active_logs}")


def read_template(name: str) -> str:
    """Carga el contenido de una plantilla de agente."""
    path = AGENTS_DIR / name
    if not path.exists():
        err(f"Template no encontrado: {path}")
        sys.exit(1)
    return path.read_text(encoding="utf-8")

def log_run(session_name: str, content: str) -> Path:
    """Guarda un registro detallado en disco con timestamp de alta precisión."""
    active_logs = get_logs_dir()
    active_logs.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]  # Incluye milisegundos para evitar colisiones
    log_file = active_logs / f"{ts}_{session_name}.log"
    log_file.write_text(
        f"=== {session_name} | {datetime.now().isoformat()} ===\n{content}",
        encoding="utf-8"
    )
    return log_file

