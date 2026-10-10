"""
Cliente de Inferencia para Modelos de Decisión System One (Kev / Jev).
"""
import httpx
from typing import Any
from pilot.core.kev_daemon import kev_daemon, BASE_URL
from pilot.core.ui import warn

class DecisionClient:
    def __init__(self):
        self.daemon = kev_daemon
        self._client = httpx.Client(timeout=300.0)

    def evaluate(self, state: str, questions: dict[str, Any]) -> dict[str, Any]:
        """
        Envía un estado y preguntas tipadas. Retorna las respuestas calibradas.
        """
        self.daemon.ensure_running()
        self.daemon.record_activity()

        payload = {
            "state": state,
            "model": "kev-latest",
            "questions": questions
        }

        try:
            resp = self._client.post(f"{BASE_URL}/v1/systemone", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("answers", {})
        except httpx.HTTPError as e:
            warn(f"  [KEV-CLIENT] Error de red al consultar Kev 4B: {e}")
            return {}

decision_client = DecisionClient()
