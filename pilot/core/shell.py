"""
Ejecutor de comandos del sistema operativo con control de timeouts.
Responsabilidad única: Ejecución de subprocesos en el shell.
"""

import subprocess

def run_command(cmd: str, cwd: str | None = None, capture: bool = True, timeout: int = 300) -> tuple[int, str, str]:
    """
    Ejecuta un comando en el shell.
    Retorna: (exit_code, stdout, stderr)
    Si excede timeout retorna (124, '', 'TIMEOUT').
    """
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"TIMEOUT: comando tardó más de {timeout} segundos"
    except Exception as e:
        return 1, "", str(e)


def run_command_args(args: list[str], cwd: str | None = None, capture: bool = True, timeout: int = 300) -> tuple[int, str, str]:
    """
    Ejecuta un comando de forma segura como lista de argumentos sin invocar el shell.
    Evita problemas de quoting y caracteres especiales en parámetros como mensajes de commit.
    """
    try:
        result = subprocess.run(
            args,
            shell=False,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"TIMEOUT: comando tardó más de {timeout} segundos"
    except Exception as e:
        return 1, "", str(e)

