import pytest
from pathlib import Path
from pilot.engines.surgery import SurgeryEngine
from pilot.engines.convergence import CumulativeMemory
import tempfile

class MockAgentRunner:
    def __init__(self, output='{"veredicto": "APROBADO", "objeciones": ""}'):
        self.output = output
        
    def run(self, prompt: str, repo_path: str, new_project: bool = True, model: str | None = None) -> tuple[int, str]:
        return 0, self.output

class MockGitClient:
    def __init__(self, repo_path):
        pass
    def run_git(self, args):
        if "diff" in args:
            return "--- a.ts\n+++ b.ts\n+ console.log('fixed')"
        return ""
    def commit(self, message):
        pass

def test_surgery_engine_grouping(monkeypatch):
    runner = MockAgentRunner()
    
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
        tf.write("""[
            {"id": "B1", "archivo": "a.ts", "descripcion": "d1"},
            {"id": "B2", "archivo": "a.ts", "descripcion": "d2"},
            {"id": "B3", "archivo": "b.ts", "descripcion": "d3"}
        ]""")
        temp_report = tf.name
        
    engine = SurgeryEngine("/tmp", runner=runner)
    monkeypatch.setattr(engine, "git", MockGitClient("/tmp"))
    
    # Overwrite decision client to prevent actual HTTP calls
    import pilot.engines.surgery
    class MockDecisionClient:
        def evaluate(self, state, schema):
            return {"is_valid_objection": {"noul": 0.1}}
    monkeypatch.setattr(pilot.engines.surgery, "decision_client", MockDecisionClient())
    
    success = engine.run_surgery_batch(temp_report)
    assert success is True
    Path(temp_report).unlink(missing_ok=True)

def test_surgery_engine_arbiter_override(monkeypatch):
    runner = MockAgentRunner('{"veredicto": "RECHAZADO", "objeciones": "Falso positivo"}')
    
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
        tf.write("""[{"id": "B1", "archivo": "a.ts", "descripcion": "d1"}]""")
        temp_report = tf.name
        
    engine = SurgeryEngine("/tmp", runner=runner)
    monkeypatch.setattr(engine, "git", MockGitClient("/tmp"))
    
    # Kev will say it is a hallucination (validity 0.1) -> patch is forced and approved
    import pilot.engines.surgery
    class MockDecisionClient:
        def evaluate(self, state, schema):
            return {"is_valid_objection": {"noul": 0.1}}
    monkeypatch.setattr(pilot.engines.surgery, "decision_client", MockDecisionClient())
    
    success = engine.run_surgery_batch(temp_report)
    assert success is True
    Path(temp_report).unlink(missing_ok=True)

def test_surgery_engine_arbiter_rejection(monkeypatch):
    runner = MockAgentRunner('{"veredicto": "RECHAZADO", "objeciones": "Bug real"}')
    
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
        tf.write("""[{"id": "B1", "archivo": "a.ts", "descripcion": "d1"}]""")
        temp_report = tf.name
        
    engine = SurgeryEngine("/tmp", runner=runner)
    
    checkout_called = False
    class MockGitRejection(MockGitClient):
        def run_git(self, args):
            if "checkout" in args:
                nonlocal checkout_called
                checkout_called = True
            if "diff" in args:
                return "diff"
            return ""
            
    monkeypatch.setattr(engine, "git", MockGitRejection("/tmp"))
    
    # Kev will say objection is valid (validity 0.9) -> patch is rejected, checkout is called
    import pilot.engines.surgery
    class MockDecisionClient:
        def evaluate(self, state, schema):
            return {"is_valid_objection": {"noul": 0.9}}
    monkeypatch.setattr(pilot.engines.surgery, "decision_client", MockDecisionClient())
    
    success = engine.run_surgery_batch(temp_report)
    assert success is True
    assert checkout_called is True
    Path(temp_report).unlink(missing_ok=True)
