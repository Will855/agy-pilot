import json
import time
from pathlib import Path
from pilot.core.decision_client import decision_client
from pilot.engines.triage import QUESTIONS_SCHEMA
from pilot.core.ui import info, ok, warn

PROMPTS_FILE = Path("/home/parz7val/scripts/agy-pilot/ALL_227_BUGS_PROMPTS.json")
OUT_FILE = Path("/home/parz7val/scripts/agy-pilot/ALL_227_BUGS_CLASSIFIED.json")
REPORT_COPY = Path("/home/parz7val/Documents/01_Proyectos_y_Codigo/Desarrollo_Web_y_Apps/petfhans-platform/docs/reports/ALL_227_BUGS_CLASSIFIED.json")

def main():
    if not PROMPTS_FILE.exists():
        raise FileNotFoundError(f"No existe {PROMPTS_FILE}")

    prompts_data = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    total_bugs = len(prompts_data)
    info(f"Cargados {total_bugs} bugs preparados para evaluación con Kev 4B.")

    # Cargar progreso previo si existe
    classified = {}
    if OUT_FILE.exists():
        try:
            existing = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            for item in existing:
                classified[item["id"]] = item
            info(f"Progreso previo detectado: {len(classified)}/{total_bugs} bugs ya clasificados. Reanudando...")
        except Exception:
            classified = {}

    # Asegurar daemon de Kev corriendo
    decision_client.daemon.ensure_running()

    batch_buffer = []
    start_time = time.time()

    for idx, bug in enumerate(prompts_data, 1):
        bug_id = bug["id"]
        if bug_id in classified:
            continue

        info(f"[{idx}/{total_bugs}] Evaluando {bug_id} ({bug['dominio']})...")
        try:
            answers = decision_client.evaluate(bug["prompt"], QUESTIONS_SCHEMA)
            
            # Filtro y cálculo de score
            hallucination_prob = (answers.get("is_hallucination") or {}).get("noul", 0.0)
            is_hallucination = hallucination_prob > 0.65

            impact = (answers.get("impact_score") or {}).get("score", 2.0)
            requires_surgery_prob = (answers.get("requires_surgery") or {}).get("patch", 0.5)

            # Score calibrado
            raw_score = (1.0 - hallucination_prob) * (requires_surgery_prob * 0.5 + 0.5) * impact

            if is_hallucination:
                kev_severity = "BAJA"
            elif raw_score >= 2.8:
                kev_severity = "CRITICA"
            elif raw_score >= 1.8:
                kev_severity = "ALTA"
            elif raw_score >= 0.9:
                kev_severity = "MEDIA"
            else:
                kev_severity = "BAJA"

            domain = (answers.get("failure_domain") or {}).get("choice", "FINTECH_SECURITY")
            skill = (answers.get("defense_skill") or {}).get("choice", "general-auditor")

            record = {
                "id": bug_id,
                "ref": bug.get("ref", ""),
                "dominio": bug.get("dominio", ""),
                "archivo": bug.get("archivo", ""),
                "descripcion": bug.get("descripcion", ""),
                "severidad_original": bug.get("severidad_original", ""),
                "severidad_kev": kev_severity,
                "score_calibrado": round(raw_score, 2),
                "prob_alucinacion": round(hallucination_prob, 2),
                "dominio_asignado": domain,
                "skill_recomendada": skill,
                "evaluado_en": time.strftime("%Y-%m-%d %H:%M:%S")
            }

            classified[bug_id] = record
            ok(f"  ✓ [{bug_id}] Kev: {kev_severity} (Original: {bug.get('severidad_original')}) | Score: {raw_score:.2f} | Skill: {skill}")

        except Exception as e:
            warn(f"  ⚠ Error al evaluar {bug_id}: {e}")
            record = {
                "id": bug_id,
                "error": str(e),
                "severidad_original": bug.get("severidad_original", ""),
                "severidad_kev": "PENDIENTE_ERROR"
            }
            classified[bug_id] = record

        # Guardado incremental inmediato (inmune a apagones/crashes)
        out_list = list(classified.values())
        OUT_FILE.write_text(json.dumps(out_list, indent=2, ensure_ascii=False), encoding="utf-8")

        # Notificación por cada bloque de 10 completados
        if len(classified) % 10 == 0:
            ok(f"\n==========================================")
            ok(f"  BLOQUE COMPLETADO: {len(classified)}/{total_bugs} BUGS")
            ok(f"==========================================\n")
            try:
                REPORT_COPY.write_text(json.dumps(out_list, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    # Final
    out_list = list(classified.values())
    OUT_FILE.write_text(json.dumps(out_list, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        REPORT_COPY.write_text(json.dumps(out_list, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    ok(f"\n¡Clasificación completada! {len(classified)}/{total_bugs} bugs procesados en {time.time() - start_time:.1f}s.")

if __name__ == "__main__":
    main()
