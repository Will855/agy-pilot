"""
Configuraciones globales, alias de modelos y constantes de agy-pilot.
"""

import os
from pathlib import Path

# Rutas de base
PILOT_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = PILOT_DIR / "agents"
DEFAULT_LOGS_DIR = PILOT_DIR / "logs"

def get_logs_dir() -> Path:
    """Retorna la ruta de logs activa, recurriendo a un directorio temporal si la ruta predeterminada no es escribible."""
    custom = os.environ.get("PILOT_LOGS_DIR")
    if custom:
        p = Path(custom).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    try:
        DEFAULT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        test_file = DEFAULT_LOGS_DIR / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        return DEFAULT_LOGS_DIR
    except OSError:
        import tempfile
        fallback = Path(tempfile.gettempdir()) / "agy_pilot_logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

LOGS_DIR = get_logs_dir()


# Parámetros de ejecución
MAX_FIX_ATTEMPTS = 3
MAX_ARGV_PROMPT = 40000

# Catálogo y alias de modelos
MODEL_ALIASES = {
    "flash": "gemini-3.8-flash-high",
    "flash-med": "gemini-3.8-flash-medium",
    "pro": "gemini-3.1-pro-high",
    "claude": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6-thinking",
}

def resolve_model(name: str) -> str:
    """Resuelve alias rápidos (flash, pro, claude, etc.) a su identificador de modelo canónico."""
    if not name or not name.strip():
        return get_default_model()
    return MODEL_ALIASES.get(name.lower().strip(), name.strip())

def get_default_model() -> str:
    raw = os.environ.get("PILOT_MODEL", "gemini-3.8-flash-high")
    if not raw or not raw.strip():
        return "gemini-3.8-flash-high"
    return resolve_model(raw)

def get_default_effort() -> str | None:
    return os.environ.get("PILOT_EFFORT", None)
