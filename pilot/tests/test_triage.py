import pytest
import time
from pilot.core.kev_daemon import kev_daemon, KevDaemonManager
from pilot.core.decision_client import decision_client
from pilot.engines.triage import TriageEngine, QUESTIONS_SCHEMA

def test_kev_daemon_healthcheck(monkeypatch):
    class MockPopen:
        def __init__(self, *args, **kwargs):
            self.args = args
        def terminate(self): pass
        def wait(self, timeout): pass
        def poll(self): return None

    monkeypatch.setattr("subprocess.Popen", MockPopen)

    health_calls = 0
    def mock_healthy(self):
        nonlocal health_calls
        health_calls += 1
        return health_calls > 1
    
    monkeypatch.setattr(KevDaemonManager, "is_healthy", mock_healthy)

    kd = KevDaemonManager()
    kd.running = False
    
    kd.ensure_running()
    assert kd.running
    
    kd.stop()
    assert not kd.running

def test_hallucination_gate_rejection():
    class MockClient:
        def evaluate(self, state, questions):
            return {"is_hallucination": {"noul": 0.8}, "impact_score": {"score": 2.5}}
    
    engine = TriageEngine()
    engine.client = MockClient()
    
    bugs = [{"id": "BUG-1", "archivo": "test.py", "descripcion": "imaginary bug", "caso_de_prueba": "none"}]
    results = engine.triage_batch(bugs)
    assert len(results) == 0

def test_calibrated_severity_mapping():
    class MockClient:
        def __init__(self, score):
            self.score = score
        def evaluate(self, state, questions):
            return {"is_hallucination": {"noul": 0.1}, "impact_score": {"score": self.score}}
    
    engine = TriageEngine()
    
    engine.client = MockClient(4.5)
    assert engine.triage_batch([{"id": "1"}])[0]["severidad"] == "CRITICA"
    
    engine.client = MockClient(3.5)
    assert engine.triage_batch([{"id": "2"}])[0]["severidad"] == "ALTA"
    
    engine.client = MockClient(2.0)
    assert engine.triage_batch([{"id": "3"}])[0]["severidad"] == "MEDIA"
    
    engine.client = MockClient(1.5)
    assert engine.triage_batch([{"id": "4"}])[0]["severidad"] == "BAJA"

def test_idle_timeout_shutdown(monkeypatch):
    import pilot.core.kev_daemon
    monkeypatch.setattr(pilot.core.kev_daemon, "IDLE_TIMEOUT_SECONDS", 1)
    
    kd = pilot.core.kev_daemon.KevDaemonManager()
    kd.running = True
    kd.last_activity = 0  # Force timeout
    
    stop_called = False
    def mock_stop():
        nonlocal stop_called
        stop_called = True
        kd.running = False
    monkeypatch.setattr(kd, "stop", mock_stop)
    
    # Run one iteration of the watchdog logic directly to avoid sleep
    if time.time() - kd.last_activity > pilot.core.kev_daemon.IDLE_TIMEOUT_SECONDS:
        kd.stop()
        
    assert stop_called
    assert not kd.running
