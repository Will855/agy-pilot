import json
import re
from pathlib import Path

repo_path = Path("/home/parz7val/Documents/01_Proyectos_y_Codigo/Desarrollo_Web_y_Apps/petfhans-platform")
p = repo_path / "docs/reports/REGISTRO_MAESTRO_DE_BUGS_Y_VULNERABILIDADES.md"
lines = p.read_text(encoding="utf-8").splitlines()

bugs = []
in_table = False
for l in lines:
    if "| ID Maestro |" in l:
        in_table = True
        continue
    if in_table and l.strip().startswith("|") and not l.strip().startswith("| :-"):
        parts = [x.strip() for x in l.split("|")[1:-1]]
        if len(parts) >= 6:
            bugs.append({
                "id": parts[0].replace("**", ""),
                "ref": parts[1].replace("`", ""),
                "dominio": parts[2],
                "severidad_original": parts[3].replace("`", ""),
                "archivo": parts[4].replace("`", ""),
                "descripcion": parts[5]
            })

prepared = []
for b in bugs:
    archivo = b["archivo"]
    dominio = b["dominio"]
    sev = b["severidad_original"]
    desc = b["descripcion"]
    
    fp = repo_path / archivo
    snippet = "Archivo no encontrado"
    if fp.exists() and fp.is_file():
        code = fp.read_text(encoding="utf-8", errors="ignore")
        flines = code.splitlines()
        
        if len(flines) <= 120:
            snippet = code
        else:
            line_m = re.search(r"l[íi]neas?\s+(\d+)", desc, re.IGNORECASE)
            target_idx = 0
            if line_m:
                target_idx = max(0, int(line_m.group(1)) - 1)
            else:
                kw = re.findall(r"[a-z]+[A-Z][a-zA-Z]*|[A-Z][a-zA-Z0-9]+[A-Z][a-zA-Z]*|[a-zA-Z]+_[a-zA-Z0-9]+", desc)
                ignored = {"Supabase", "PostgreSQL", "NextRequest", "NextResponse", "Stripe", "Realtime", "PubSub", "Deepgram"}
                kw = [w for w in kw if w not in ignored]
                for w in kw:
                    found = False
                    for idx, line_text in enumerate(flines):
                        if w in line_text:
                            target_idx = idx
                            found = True
                            break
                    if found:
                        break
            
            start = max(0, target_idx - 15)
            end = min(len(flines), target_idx + 45)
            snippet = "\n".join(flines[start:end])

    prompt = (
        f"File: {archivo}\n"
        f"Domain: {dominio}\n"
        f"Reported Severity: {sev}\n"
        f"Observed Issue: {desc}\n\n"
        f"Relevant Code Context:\n```typescript\n{snippet}\n```"
    )

    prepared.append({
        "id": b["id"],
        "ref": b["ref"],
        "dominio": dominio,
        "severidad_original": sev,
        "archivo": archivo,
        "descripcion": desc,
        "prompt": prompt,
        "snippet_lines": len(snippet.splitlines())
    })

out_file = Path("/home/parz7val/scripts/agy-pilot/ALL_227_BUGS_PROMPTS.json")
out_file.write_text(json.dumps(prepared, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Éxito: {len(prepared)} prompts listos guardados en {out_file}")
