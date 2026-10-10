import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.runner import default_runner
from config import resolve_model

repo_path = "/home/parz7val/Documents/01_Proyectos_y_Codigo/Desarrollo_Web_y_Apps/petfhans-platform"
bugs_file = Path(repo_path) / "docs/reports/REGISTRO_MAESTRO_DE_BUGS_Y_VULNERABILIDADES.md"

lines = bugs_file.read_text().splitlines()
raw_bugs = []
for line in lines:
    if line.startswith('| **'):
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 6:
            id_clean = parts[1].replace('**', '')
            if 'SEC' in id_clean or 'BUG' in id_clean:
                raw_bugs.append({
                    "id": id_clean,
                    "dominio": parts[3],
                    "severidad_original": parts[4].replace('`', ''),
                    "archivo": parts[5].replace('`', ''),
                    "descripcion": parts[6]
                })

def process_bug(bug):
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
        try:
            _, extracted = default_runner.run(prompt, repo_path, new_project=True, model=resolve_model("flash"))
            snippet = extracted.strip()
        except Exception as e:
            snippet = f"Error en extracción: {str(e)}"
    else:
        snippet = "Archivo no encontrado"
        
    print(f"Completado: {bug['id']}")
    return {
        "id": bug['id'],
        "archivo": bug['archivo'],
        "descripcion": bug['descripcion'],
        "severidad_original": bug['severidad_original'],
        "contexto_verificable": snippet
    }

prepared = []
with ThreadPoolExecutor(max_workers=25) as executor:
    futures = [executor.submit(process_bug, bug) for bug in raw_bugs]
    for future in as_completed(futures):
        prepared.append(future.result())

out_path = Path("ALL_227_BUGS_PREPARED.json")
out_path.write_text(json.dumps(prepared, indent=2))
print(f"\nCompletado! {len(prepared)} bugs guardados en {out_path.absolute()}")
