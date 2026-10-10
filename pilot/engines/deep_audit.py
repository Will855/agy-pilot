"""
Motor de auditoría profunda de un archivo único (audit).
Responsabilidad única: Bucle de agotamiento de 4 lentes temáticas con validación fiscal de falsos positivos.
"""

import json
import sys
from pathlib import Path

from pilot.core.parser import extract_json
from pilot.core.runner import AgentRunner, default_runner
from pilot.core.storage import log_run
from pilot.core.ui import Colors, banner, err, info, ok, warn

LENSES = [
    (
        "Casos_borde_y_tipos",
        "Solo busca: valores nulos no manejados, arrays vacíos, divisiones por cero, tipos incompatibles, índices OOB.",
    ),
    (
        "Concurrencia_y_estado",
        "Solo busca: condiciones de carrera, estado compartido mutable, recursos sin liberar, llamadas bloqueantes.",
    ),
    (
        "Seguridad_y_validacion",
        "Solo busca: inyecciones SQL/OS/NoSQL, datos sin sanitizar, secrets hardcodeados, permisos mal validados.",
    ),
    (
        "Errores_silenciosos",
        "Solo busca: try/catch vacíos o mudos, promesas sin .catch(), retornos ignorados, fallos de red sin manejo.",
    ),
]

def deep_audit_loop(
    target_file: str,
    repo: str,
    max_rounds: int = 5,
    runner: AgentRunner | None = None,
) -> list[dict]:
    banner("MODO AUDITORÍA PROFUNDA — Bucle de Agotamiento", Colors.YELLOW)
    info(f"Objetivo: {target_file}")
    info(f"Rondas máximas: {max_rounds}")

    active_runner = runner or default_runner
    file_path = Path(repo) / target_file
    if not file_path.exists():
        err(f"Archivo no encontrado: {file_path}")
        sys.exit(1)

    code_content = file_path.read_text(encoding="utf-8", errors="replace")
    info(f"Archivo: {len(code_content)} chars, {code_content.count(chr(10))} líneas")

    known_bugs: list[dict] = []
    all_findings: list[dict] = []

    for round_num in range(1, max_rounds + 1):
        banner(f"Ronda {round_num}/{max_rounds}", Colors.YELLOW)
        round_findings: list[dict] = []

        for lens_id, lens_instruction in LENSES:
            info(f"Lente: {lens_id.replace('_', ' ')}")
            known_str = json.dumps(known_bugs, ensure_ascii=False)[:1500] if known_bugs else "Ninguno aún."

            prompt = f"""# ROL: Cazador de Bugs — Lente: {lens_id.replace('_', ' ')}

## ARCHIVO A AUDITAR
Ruta: `{target_file}`

```
{code_content[:5500]}
```

## INSTRUCCIÓN DE ESTA LENTE
{lens_instruction}

## BUGS YA CONOCIDOS (NO los repitas, busca uno diferente)
{known_str}

## REGLA DEL ABOGADO DEL DIABLO
Asume que este código TIENE al menos 1 problema real bajo esta lente específica.
Si no puedes demostrar un bug con un caso de prueba concreto (input → output incorrecto),
responde EXACTAMENTE: `LENTE_LIMPIA`
No respondas `LENTE_LIMPIA` sin antes hacer un análisis profundo.

## FORMATO SI ENCUENTRAS UN BUG
1. **Descripción:** qué está mal y en qué línea aproximada
2. **Caso de prueba:** `input exacto → output incorrecto observado`
3. **Por qué es un bug real** y no una alucinación teórica
"""
            _, output = active_runner.run(prompt, repo, new_project=True)
            log_run(f"deep_r{round_num}_{lens_id}", output or "(sin output)")

            if not output or "LENTE_LIMPIA" in output:
                info(f"  → Lente limpia ({lens_id})")
            else:
                round_findings.append({
                    "ronda": round_num,
                    "lente": lens_id,
                    "hallazgo": output[:600],
                })
                ok(f"  → Posible hallazgo bajo '{lens_id}'")

        if not round_findings:
            ok(f"\nCriterio de parada: ronda {round_num} sin nuevos hallazgos.")
            break

        # Verificación fiscal
        info("Verificando hallazgos con agente fiscal...")
        fiscal_prompt = f"""# ROL: Fiscal Verificador de Bugs

Tienes estos hallazgos reportados sobre `{target_file}`:

{json.dumps(round_findings, ensure_ascii=False, indent=2)}

Para CADA hallazgo determina:
1. ¿El caso de prueba es concreto y reproducible?
2. ¿El código efectivamente fallaría con ese input?
3. ¿Es un bug real o una alucinación teórica?

Responde EXACTAMENTE en este JSON (sin texto adicional):
{{"verificados": [{{"hallazgo_index": 0, "es_real": true, "razon": "explicación breve"}}]}}
"""
        _, fiscal_output = active_runner.run(fiscal_prompt, repo, new_project=True)

        try:
            fiscal = extract_json(fiscal_output, context="fiscal")
            verified = [v for v in fiscal.get("verificados", []) if v.get("es_real")] if isinstance(fiscal, dict) else []
            if verified:
                ok(f"{len(verified)} bug(s) confirmado(s) como reales")
                for v in verified:
                    idx = v.get("hallazgo_index", 0)
                    if 0 <= idx < len(round_findings):
                        entry = {**round_findings[idx], "razon_fiscal": v.get("razon", "")}
                        known_bugs.append(entry)
                        all_findings.append(entry)
            else:
                ok("Ningún hallazgo confirmado como bug real — auditoría completa.")
                break
        except ValueError:
            warn("Fiscal no pudo parsear JSON — anotando hallazgos sin verificar")
            known_bugs.extend(round_findings)
            all_findings.extend(round_findings)

    # Reporte final
    banner("REPORTE FINAL DE AUDITORÍA PROFUNDA", Colors.GREEN)
    report_path = log_run("deep_audit_final", json.dumps(all_findings, ensure_ascii=False, indent=2))
    ok(f"Bugs confirmados: {len(all_findings)}")
    ok(f"Reporte: {report_path}")

    if all_findings:
        print(f"\n{Colors.BOLD}Siguiente paso:{Colors.RESET}")
        print("  Ejecuta una sesión nueva de agy con el reporte para planear la refactorización:")
        print("  agy-pilot run --ticket \"Corregir bugs de auditoría\" (usando el reporte)")

    return all_findings
