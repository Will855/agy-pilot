#!/usr/bin/env python3
"""
agy-pilot — Orquestador de desarrollo asistido por IA (Entrypoint & Facade)
El sistema ha sido refactorizado bajo principios SOLID dentro del paquete `pilot/`.
Este archivo actúa como punto de entrada y fachada retrocompatible.
"""

import sys
from pathlib import Path

# Asegurar que el directorio raíz de agy-pilot esté en el sys.path
PILOT_ROOT = Path(__file__).resolve().parent
if str(PILOT_ROOT) not in sys.path:
    sys.path.insert(0, str(PILOT_ROOT))

# Re-exports para retrocompatibilidad
from pilot.cli import main
from pilot.config import (
    AGENTS_DIR,
    LOGS_DIR,
    MAX_FIX_ATTEMPTS,
    MODEL_ALIASES,
    PILOT_DIR,
    resolve_model,
)
from pilot.core.git import GitClient
from pilot.core.parser import extract_json
from pilot.core.runner import AgyRunner, default_runner, run_agy
from pilot.core.shell import run_command as run
from pilot.core.scope import ScopeContract, ScopeDiscoveryEngine
from pilot.core.storage import log_run, read_template
from pilot.core.ui import Colors as C, Timer as _Timer, banner, err, info, ok, step, warn

from pilot.engines.convergence import (
    CumulativeMemory,
    Quadrant,
    partition_into_quadrants,
    run_convergence_loop,
)
from pilot.engines.deep_audit import deep_audit_loop
from pilot.engines.doctor import run_doctor
from pilot.engines.pipeline import (
    phase_audit,
    phase_document,
    phase_implement,
    phase_plan,
    phase_pr,
    phase_review,
)
from pilot.engines.sweep import continuous_sweep


if __name__ == "__main__":
    main()
