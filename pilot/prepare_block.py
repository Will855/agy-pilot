import json
import os
from pathlib import Path
from core.runner import default_runner
from config import resolve_model

repo_path = "/home/parz7val/Documents/01_Proyectos_y_Codigo/Desarrollo_Web_y_Apps/petfhans-platform"
bugs_file = Path(repo_path) / "docs/reports/REGISTRO_MAESTRO_DE_BUGS_Y_VULNERABILIDADES.md"

lines = bugs_file.read_text().splitlines()
raw_bugs = []
for line in lines:
    if line.startswith('| **PAY-SEC'):
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 6:
            raw_bugs.append({
                "id": parts[1].replace('**', ''),
                "dominio": parts[3],
                "severidad_original": parts[4].replace('`', ''),
                "archivo": parts[5].replace('`', ''),
                "descripcion": parts[6]
            })

block_0 = raw_bugs[:10]
prepared = []

for bug in block_0:
    print(f"Extrayendo contexto para {bug['id']}...")
    file_path = Path(repo_path) / bug['archivo']
    if file_path.exists():
        raw_content = file_path.read_text()[:20000]
        prompt = f"""
Extrae TODO el bloque o bloques de código de este archivo que estén relacionados con el siguiente bug. 
No te limites a un número de líneas. Extrae todo lo necesario para que un auditor de ciberseguridad pueda validar la vulnerabilidad sin quedarse a ciegas.

Bug: {bug['descripcion']}

Archivo:
{raw_content}

Solo devuelve el código crudo, sin formato markdown ni explicaciones adicionales.
"""
        _, extracted = default_runner.run(prompt, repo_path, new_project=True, model=resolve_model("flash"))
        snippet = extracted.strip()
    else:
        snippet = "Archivo no encontrado"
        
    prepared.append({
        "id": bug['id'],
        "archivo": bug['archivo'],
        "descripcion": bug['descripcion'],
        "severidad_original": bug['severidad_original'],
        "contexto_verificable": snippet
    })

out_path = Path("BLOCK_0_PREPARED_FOR_KEV.json")
out_path.write_text(json.dumps(prepared, indent=2))
print(f"Completado. Guardado en {out_path.absolute()}")
