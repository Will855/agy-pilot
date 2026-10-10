"""
Gestor de ciclo de vida para el servidor local de Kev (FastAPI /v1/systemone).
Implementa Auto-Sleep / Idle Watchdog de 5 minutos y arranque transparente.
"""
import os
import subprocess
import threading
import time
import httpx
from pathlib import Path
from pilot.core.ui import info, ok, warn

KEV_DIR = Path("/home/parz7val/opt/kev")
UV_BIN = Path("/home/parz7val/.local/bin/uv")
PORT = 8008
BASE_URL = f"http://127.0.0.1:{PORT}"
IDLE_TIMEOUT_SECONDS = 300  # 5 minutos

class KevDaemonManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.process: subprocess.Popen | None = None
        self.last_activity = 0.0
        self.watchdog_thread: threading.Thread | None = None
        self.running = False

    def is_healthy(self) -> bool:
        try:
            r = httpx.get(f"{BASE_URL}/v1/models", timeout=0.8)
            return r.status_code == 200
        except Exception:
            return False

    def ensure_running(self):
        with self._lock:
            self.last_activity = time.time()
            if self.is_healthy():
                return

            info("  [KEV-DAEMON] Levantando servidor Kev 4B en segundo plano...")
            env = os.environ.copy()
            env["KEV_DTYPE"] = "bf16"
            env["KEV_PREFIX_CACHE"] = "8"

            cmd = [
                str(UV_BIN), "run", "--extra", "serve",
                "python", "-m", "kev.serve",
                "--run", "jaredpalmer/kev-4b",
                "--port", str(PORT)
            ]

            self.process = subprocess.Popen(
                cmd,
                cwd=str(KEV_DIR),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Esperar arranque (mmap safetensors: ~1.5 a 3.0s)
            start_time = time.time()
            while time.time() - start_time < 120:
                if self.process and self.process.poll() is not None:
                    code = self.process.poll()
                    self.process = None
                    raise RuntimeError(f"Kev 4B crasheó al iniciar (exit code {code}).")
                
                if self.is_healthy():
                    ok(f"  ✓ Kev 4B listo y escuchando en {BASE_URL} ({time.time() - start_time:.1f}s)")
                    self.running = True
                    self._start_watchdog()
                    return
                time.sleep(0.3)

            # Timeout
            if self.process:
                self.process.terminate()
                self.process = None
            raise RuntimeError("Tiempo de espera agotado al arrancar Kev 4B.")

    def record_activity(self):
        self.last_activity = time.time()

    def _start_watchdog(self):
        if self.watchdog_thread and self.watchdog_thread.is_alive():
            return
        self.watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self.watchdog_thread.start()

    def _watchdog_loop(self):
        while self.running:
            time.sleep(15)
            should_stop = False
            with self._lock:
                if time.time() - self.last_activity > IDLE_TIMEOUT_SECONDS:
                    should_stop = True
            
            if should_stop:
                info("  [KEV-DAEMON] 5 minutos de inactividad detectados. Apagando Kev para liberar RAM...")
                self.stop()
                break

    def stop(self):
        with self._lock:
            self.running = False
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                self.process = None
            ok("  ✓ Proceso de Kev 4B finalizado. RAM liberada al 100%.")

kev_daemon = KevDaemonManager()
