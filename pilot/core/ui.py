"""
Interfaz de consola, formato de colores, banners y temporizadores.
Responsabilidad única: Presentación visual en la terminal.
"""

import time

class Colors:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BLUE   = "\033[94m"
    MAGENTA = "\033[95m"
    GRAY   = "\033[90m"

C = Colors

def banner(text: str, color: str = Colors.CYAN) -> None:
    width = 62
    print(f"\n{color}{Colors.BOLD}{'─' * width}")
    print(f"  {text}")
    print(f"{'─' * width}{Colors.RESET}\n")

def step(num: int, text: str) -> None:
    print(f"{Colors.BLUE}{Colors.BOLD}[Paso {num}]{Colors.RESET} {text}")

def ok(text: str) -> None:
    print(f"{Colors.GREEN}  ✓ {text}{Colors.RESET}")

def warn(text: str) -> None:
    print(f"{Colors.YELLOW}  ⚠ {text}{Colors.RESET}")

def err(text: str) -> None:
    print(f"{Colors.RED}  ✗ {text}{Colors.RESET}")

def info(text: str) -> None:
    print(f"{Colors.GRAY}  → {text}{Colors.RESET}")

class Timer:
    """Context manager para medir y reportar la duración de una fase o llamada."""
    def __init__(self, label: str):
        self.label = label
        self._start = 0.0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *_):
        elapsed = time.time() - self._start
        info(f"Duración de '{self.label}': {elapsed:.1f}s")
