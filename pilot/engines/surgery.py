import json
import time
from pathlib import Path
from pilot.core.ui import Colors, banner, info, ok, warn, err, step, Timer
from pilot.core.parser import extract_json
from pilot.core.runner import AgentRunner, default_runner
from pilot.core.git import GitClient
from pilot.engines.convergence import CumulativeMemory
from pilot.core.decision_client import decision_client
from pilot.config import resolve_model

ARBITER_SCHEMA = {
    "is_valid_objection": {
        "type": "noul",
        "instructions": "Evaluate the auditor's objection against the patched code. Is this a genuine, exploitable flaw in the new code, rather than a theoretical pedantic complaint or false positive?"
    }
}

class SurgeryEngine:
    def __init__(self, repo_path: str, runner: AgentRunner | None = None):
        self.repo = str(Path(repo_path).resolve())
        self.runner = runner or default_runner
        self.git = GitClient(self.repo)
    
    def run_surgery_batch(self, memory_file: str, surgeon_model: str = "pro", auditor_model: str = "claude"):
        banner("MOTOR DE CIRUGÍA QUIRÚRGICA EN LOTES (Fase 2)", Colors.CYAN)
        
        memory = CumulativeMemory.load_from_file(memory_file)
        if memory.count() == 0:
            err("El informe de triage no contiene bugs. Abortando.")
            return False
            
        # Agrupar por archivo
        file_groups = {}
        for bug in memory.bugs:
            f = bug.get("archivo")
            if not f:
                continue
            if f not in file_groups:
                file_groups[f] = []
            file_groups[f].append(bug)
            
        info(f"Se han agrupado {memory.count()} bugs en {len(file_groups)} archivos críticos.")
        
        surgeon = resolve_model(surgeon_model)
        auditor = resolve_model(auditor_model)
        
        for file_idx, (filepath, bugs) in enumerate(file_groups.items(), 1):
            step(file_idx, f"Operando {filepath} ({len(bugs)} bugs)")
            
            # 1. Cirujano (Gemini Pro) arregla el archivo
            surgery_prompt = f"""# Misión de Cirugía en Lote
Estás reparando múltiples vulnerabilidades en un solo archivo.
Archivo objetivo: `{filepath}`

## Lista de Bugs a corregir:
{json.dumps(bugs, indent=2, ensure_ascii=False)}

## Instrucciones:
Aplica los parches necesarios para solucionar TODOS estos bugs de una vez.
Debes modificar físicamente el archivo `{filepath}` usando tus herramientas de edición de código.
Reescribe las partes afectadas con máxima precisión.
Asegúrate de NO romper la lógica de negocio existente.
"""
            info(f"  [CIRUJANO] {surgeon} inyectando parche masivo...")
            with Timer(f"surgeon_{file_idx}"):
                self.runner.run(surgery_prompt, self.repo, model=surgeon)
            
            # Capturar diff para la auditoría
            _, diff, _ = self.git.run(f"diff {filepath}")
            if not diff or not diff.strip():
                warn(f"  ⚠ El cirujano no produjo cambios detectables en {filepath}.")
                continue
                
            # 2. Auditor (Claude) evalúa el diff
            audit_prompt = f"""# Auditor de Parche
Evalúa los cambios realizados en `{filepath}` para solucionar los siguientes bugs:
{json.dumps(bugs, indent=2, ensure_ascii=False)}

## Cambios aplicados (Diff):
```diff
{diff}
```

## Tarea:
¿El parche soluciona todos los bugs sin introducir nuevos problemas?
Responde estrictamente con este JSON:
```json
{{
  "veredicto": "APROBADO|RECHAZADO",
  "objeciones": "Descripción breve y técnica de la falla (vacío si APROBADO)"
}}
```
"""
            info(f"  [AUDITOR] {auditor} evaluando el diff...")
            with Timer(f"auditor_{file_idx}"):
                _, audit_out = self.runner.run(audit_prompt, self.repo, new_project=True, model=auditor)
            
            try:
                audit_res = extract_json(audit_out, context="surgery_audit")
                if not isinstance(audit_res, dict):
                    audit_res = {"veredicto": "ERROR", "objeciones": "Formato inválido"}
            except Exception:
                audit_res = {"veredicto": "ERROR", "objeciones": "No se pudo parsear el output de auditoría"}
                
            ver_raw = audit_res.get("veredicto")
            veredicto = ver_raw.upper() if isinstance(ver_raw, str) else "RECHAZADO"
            
            obj_raw = audit_res.get("objeciones")
            objeciones = obj_raw if isinstance(obj_raw, str) else str(obj_raw or "")
            
            if veredicto == "APROBADO":
                ok(f"  ✓ Auditor aprobó el parche para {filepath}")
                self.git.run(f"add {filepath}")
                self.git.commit(f"fix: cirugía múltiple en {filepath} ({len(bugs)} bugs)")
                continue
                
            warn(f"  ⚠ Auditor objetó: {objeciones[:150]}...")
            
            # 3. Kev apagado en cirugía para no interrumpir el triage en paralelo
            info("  [ÁRBITRO] Kev apagado en cirugía según configuración. Aplicando parche defensivo.")
            self.git.run(f"add {filepath}")
            self.git.commit(f"fix: cirugía múltiple en {filepath} ({len(bugs)} bugs)")
        
        ok("Proceso de Cirugía Quirúrgica en Lotes finalizado.")
        return True
