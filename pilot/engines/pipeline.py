"""
Motor de pipeline completo de desarrollo (run): Ticket → Auditoría → Plan → Implementación → Review → Docs → PR.
Responsabilidad única: Orquestación del ciclo de vida del desarrollo atómico.
"""

import json
import subprocess
import sys
import time

from pilot.config import LOGS_DIR, MAX_FIX_ATTEMPTS
from pilot.core.git import GitClient
from pilot.core.parser import extract_json
from pilot.core.runner import AgentRunner, default_runner
from pilot.core.shell import run_command
from pilot.core.storage import log_run, read_template
from pilot.core.ui import Colors, Timer, banner, err, info, ok, step, warn

def phase_audit(ticket: str, repo: str, runner: AgentRunner) -> dict:
    banner("FASE 1 — Auditoría de Impacto (solo lectura)", Colors.CYAN)
    template = read_template("00_auditor.md")
    prompt = template.replace("{TICKET}", ticket).replace("{REPO_PATH}", repo)

    info("Consultando agente auditor...")
    with Timer("agente auditor"):
        _, output = runner.run(prompt, repo)
    log_path = log_run("01_audit", f"TICKET:\n{ticket}\n\nOUTPUT:\n{output}")
    info(f"Log guardado: {log_path.name}")

    if not output:
        warn("El agente auditor no retornó output. Continuando con reporte vacío.")
        return {"estimacion_complejidad": "DESCONOCIDA", "archivos_afectados": [], "riesgos": []}

    try:
        report = extract_json(output, context="auditor")
        if isinstance(report, dict):
            estimacion = report.get('estimacion_complejidad') or '?'
            archivos = report.get('archivos_afectados') or []
            riesgos = report.get('riesgos') or []
            ok(f"Complejidad: {estimacion}")
            ok(f"Archivos afectados: {len(archivos)}")
            for r in riesgos:
                if isinstance(r, dict) and r.get("nivel") == "ALTO":
                    descripcion = r.get('descripcion') or ''
                    warn(f"Riesgo ALTO: {descripcion[:80]}")
            return report
        return {"raw_audit": output, "estimacion_complejidad": "DESCONOCIDA"}
    except ValueError:
        warn("Usando reporte de auditoría en formato libre (sin JSON estructurado)")
        return {"raw_audit": output, "estimacion_complejidad": "DESCONOCIDA"}

def phase_plan(ticket: str, audit_report: dict, repo: str, runner: AgentRunner) -> dict:
    banner("FASE 2 — Plan de Micro-Tareas", Colors.CYAN)
    _, stack_info, _ = run_command(
        "head -20 package.json 2>/dev/null || "
        "head -20 pyproject.toml 2>/dev/null || "
        "head -20 requirements.txt 2>/dev/null || "
        "echo 'Stack no detectado'",
        cwd=repo
    )

    template = read_template("01_planner.md")
    prompt = (
        template
        .replace("{TICKET}", ticket)
        .replace("{AUDIT_REPORT}", json.dumps(audit_report, ensure_ascii=False, indent=2)[:2000])
        .replace("{STACK_INFO}", stack_info[:800])
    )

    info("Generando plan de micro-tareas...")
    _, output = runner.run(prompt, repo)
    log_run("02_plan", output)

    if not output:
        err("El planificador no retornó output.")
        sys.exit(1)

    try:
        plan = extract_json(output, context="planificador")
        if not isinstance(plan, dict):
            raise ValueError("El plan no es un objeto JSON.")
    except ValueError:
        err("No se pudo parsear el plan. Revisa los logs.")
        sys.exit(1)

    tasks = plan.get("micro_tareas", [])
    if not tasks:
        warn("El plan no contiene micro-tareas. Verifica el prompt del planificador.")

    ok(f"{len(tasks)} micro-tarea(s) generadas")
    for t in tasks:
        info(f"  [{t.get('id','?')}] {t.get('titulo','')}")
        vcmd = t.get("comando_verificacion", "N/A")
        if vcmd and vcmd != "N/A":
            info(f"      ✓ Verificación: {vcmd[:70]}")
        else:
            warn("      ⚠ Sin comando de verificación")
    return plan

def phase_implement(plan: dict, repo: str, ticket: str, runner: AgentRunner, git_client: GitClient) -> tuple[list[dict], str]:
    banner("FASE 3+4 — Implementación Atómica + Bucle de Corrección", Colors.CYAN)
    branch = plan.get("rama_git") or f"feature/pilot-{int(time.time())}"
    tasks = plan.get("micro_tareas") or []
    
    raw_order = plan.get("orden_ejecucion")
    if raw_order is None:
        order = [str(t.get("id")) for t in tasks if t.get("id") is not None]
    else:
        order = [str(x) for x in raw_order if x is not None]
        
    task_map = {str(t.get("id")): t for t in tasks if t.get("id") is not None}

    step(0, f"Creando rama: {branch}")
    if git_client.create_branch(branch):
        ok(f"Rama '{branch}' lista")
    else:
        err("No se pudo crear/cambiar a la rama.")
        sys.exit(1)

    results: list[dict] = []
    last_error = ""

    for task_id in order:
        task = task_map.get(task_id)
        if not task:
            warn(f"Tarea {task_id} no encontrada, omitiendo.")
            continue

        task_titulo = task.get("titulo") or f"Tarea {task_id}"
        task_descripcion = task.get("descripcion") or ""
        archivos = task.get("archivos_a_modificar") or []
        task_contexto = task.get("contexto_necesario") or ""
        verify_cmd = task.get("comando_verificacion") or ""

        step(task_id, task_titulo)
        success = False

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            if attempt == 1:
                template = read_template("02_implementer.md")
                prompt = (
                    template
                    .replace("{REPO_PATH}", repo)
                    .replace("{BRANCH_NAME}", branch)
                    .replace("{TASK_TITLE}", task_titulo)
                    .replace("{TASK_DESCRIPTION}", task_descripcion)
                    .replace("{FILES_TO_MODIFY}", ", ".join(archivos))
                    .replace("{CODE_CONTEXT}", task_contexto)
                    .replace("{ERROR_CONTEXT}", "")
                    .replace("{VERIFICATION_CMD}", verify_cmd)
                )
            else:
                info(f"  Intento #{attempt} — sesión de corrección (error anterior capturado)")
                template = read_template("03_fixer.md")
                prompt = (
                    template
                    .replace("{REPO_PATH}", repo)
                    .replace("{BRANCH_NAME}", branch)
                    .replace("{TASK_TITLE}", task_titulo)
                    .replace("{TASK_DESCRIPTION}", task_descripcion)
                    .replace("{FILES_MODIFIED}", ", ".join(archivos))
                    .replace("{ERROR_OUTPUT}", last_error[:2000])
                    .replace("{VERIFICATION_CMD}", verify_cmd)
                    .replace("{ATTEMPT_NUMBER}", str(attempt))
                )

            info(f"  Llamando agente (intento {attempt}/{MAX_FIX_ATTEMPTS})...")
            _, agent_output = runner.run(prompt, repo, new_project=True)
            log_run(f"03_task{task_id}_attempt{attempt}", agent_output or "(sin output)")

            if "ESCALACION_REQUERIDA" in (agent_output or ""):
                err(f"Escalación requerida en tarea {task_id}: revisar manualmente.")
                break

            # Verificación de terminal
            if verify_cmd:
                info(f"  Verificando: {verify_cmd[:70]}")
                v_code, v_out, v_err = run_command(verify_cmd, cwd=repo)
                
                if v_code == 124 and "TIMEOUT:" in v_err:
                    warn("  El comando de verificación tardó demasiado (>5 min). Saltando.")
                    break

                if v_code == 0:
                    ok("Verificación pasó ✓")
                    git_client.commit(f"feat: {task_titulo} [pilot-{task_id}]")
                    ok("Commit guardado")
                    results.append({"task": task, "status": "OK", "attempts": attempt})
                    success = True
                    break
                else:
                    last_error = f"CMD: {verify_cmd}\nEXIT: {v_code}\nSTDOUT:\n{v_out}\nSTDERR:\n{v_err}"
                    err(f"Verificación falló (exit {v_code})")
                    info(f"  Error (primeras 200 chars): {(v_err or v_out)[:200]}")
                    if attempt == MAX_FIX_ATTEMPTS:
                        results.append({"task": task, "status": "FAILED", "attempts": attempt, "error": last_error[:500]})
            else:
                warn("Sin comando de verificación — se asume éxito.")
                git_client.commit(f"feat: {task_titulo} [pilot-{task_id}]")
                results.append({"task": task, "status": "NO_VERIFY", "attempts": attempt})
                success = True
                break

        if not success:
            err(f"Tarea {task_id} falló tras {MAX_FIX_ATTEMPTS} intentos.")
            print(f"\n{Colors.YELLOW}¿Qué hacer?{Colors.RESET}")
            print("  [s] Saltar esta tarea y continuar con la siguiente")
            print("  [a] Abortar el pipeline")
            try:
                choice = input("Elige [s/a]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "a"
            if choice == "a":
                err("Pipeline abortado.")
                sys.exit(1)
            warn(f"Tarea {task_id} omitida. Continuando...")

    return results, branch

def phase_review(ticket: str, branch: str, repo: str, base: str, runner: AgentRunner, git_client: GitClient) -> dict:
    banner("FASE 5 — Code Review Independiente (4 Lentes)", Colors.CYAN)
    diff = git_client.diff_vs_base(base)
    if diff == "(sin cambios detectados)":
        warn("No se detectaron cambios para revisar.")
        return {"veredicto": "SIN_CAMBIOS", "hallazgos": []}

    info(f"Diff: {len(diff)} caracteres, ~{diff.count(chr(10))} líneas")

    template = read_template("04_reviewer.md")
    prompt = (
        template
        .replace("{TICKET}", ticket)
        .replace("{BRANCH_NAME}", branch)
        .replace("{GIT_DIFF}", diff[:7000])
    )

    info("Ejecutando auditor independiente...")
    _, output = runner.run(prompt, repo, new_project=True)
    log_path = log_run("04_review", output or "(sin output)")
    info(f"Log guardado: {log_path.name}")

    if not output:
        warn("El revisor no retornó output. Verifica el log.")
        return {"veredicto": "ERROR", "hallazgos": [], "raw": ""}

    try:
        review = extract_json(output, context="code-review")
        if isinstance(review, dict):
            veredicto = review.get("veredicto") or "DESCONOCIDO"
            color = (Colors.GREEN if veredicto == "APROBADO"
                     else Colors.YELLOW if "OBSERVACIONES" in veredicto
                     else Colors.RED)
            print(f"\n  Veredicto: {color}{Colors.BOLD}{veredicto}{Colors.RESET}")
            hallazgos = review.get("hallazgos") or []
            criticos = [h for h in hallazgos if isinstance(h, dict) and h.get("severidad") == "CRITICA"]
            if criticos:
                err(f"Hallazgos CRÍTICOS: {len(criticos)}")
            if hallazgos:
                warn(f"Total de hallazgos: {len(hallazgos)}")
            return review
        return {"veredicto": "MANUAL_REVIEW_NEEDED", "hallazgos": [], "raw": output[:1000]}
    except ValueError:
        warn("Review en texto libre (sin JSON). Guardado en log.")
        return {"veredicto": "MANUAL_REVIEW_NEEDED", "hallazgos": [], "raw": output[:1000]}

def phase_document(ticket: str, branch: str, results: list, review: dict, repo: str, base: str, runner: AgentRunner, git_client: GitClient) -> str:
    banner("FASE 6 — Documentación", Colors.CYAN)
    diff = git_client.diff_vs_base(base)
    completed = [r["task"].get("titulo","") for r in results if r.get("status") == "OK"]

    template = read_template("05_documenter.md")
    prompt = (
        template
        .replace("{TICKET}", ticket)
        .replace("{BRANCH_NAME}", branch)
        .replace("{COMPLETED_TASKS}", "\n".join(f"- {t}" for t in completed) or "(ninguna)")
        .replace("{AUDIT_REPORT}", json.dumps(review, ensure_ascii=False)[:1500])
        .replace("{GIT_DIFF}", diff[:5000])
    )

    info("Generando documentación...")
    _, output = runner.run(prompt, repo, new_project=True)
    log_run("05_docs", output or "(sin output)")
    ok("Documentación generada")
    return output or "(sin documentación generada)"

def phase_pr(ticket: str, branch: str, docs: str, review: dict, repo: str, git_client: GitClient) -> str:
    banner("FASE 7 — Creando Draft PR", Colors.CYAN)
    veredicto = review.get("veredicto", "PENDIENTE")
    hallazgos = review.get("hallazgos", [])
    hallazgos_json = json.dumps(hallazgos, ensure_ascii=False, indent=2)

    pr_body = f"""## 🤖 Generado por agy-pilot
{docs}

---

## 🔍 Reporte del Auditor Independiente
**Veredicto:** `{veredicto}`
**Hallazgos:** {len(hallazgos)}

<details>
<summary>Ver detalle de hallazgos</summary>

```json
{hallazgos_json}
```

</details>

---
> ⚠️ PR generada automáticamente. Revisa el reporte del auditor antes de aprobar.
"""
    pr_title = f"[PILOT] {ticket[:70]}"
    url = git_client.push_and_create_pr(branch, pr_title, pr_body)
    if url.startswith("http"):
        ok(f"Draft PR: {url}")
    else:
        warn(url)
    return url

def execute_pipeline(
    ticket: str,
    repo: str,
    base: str = "main",
    skip_pr: bool = False,
    no_review: bool = False,
    runner: AgentRunner | None = None,
) -> None:
    active_runner = runner or default_runner
    git_client = GitClient(repo)

    banner("🚀 agy-pilot — Pipeline de Desarrollo", Colors.GREEN)
    info(f"Repo: {repo}")
    info(f"Ticket: {ticket[:90]}")
    info(f"Logs: {LOGS_DIR}")
    print()

    audit_report = phase_audit(ticket, repo, active_runner)

    print(f"\n{Colors.BOLD}¿Proceder con la implementación? [s/n]{Colors.RESET} ", end="", flush=True)
    try:
        if input().strip().lower() != "s":
            warn("Pipeline cancelado. Informe de auditoría guardado en logs/.")
            sys.exit(0)
    except (EOFError, KeyboardInterrupt):
        warn("Cancelado.")
        sys.exit(0)

    plan = phase_plan(ticket, audit_report, repo, active_runner)
    results, branch = phase_implement(plan, repo, ticket, active_runner, git_client)

    review = {}
    if not no_review:
        review = phase_review(ticket, branch, repo, base, active_runner, git_client)

    docs = phase_document(ticket, branch, results, review, repo, base, active_runner, git_client)

    if not skip_pr:
        phase_pr(ticket, branch, docs, review, repo, git_client)

    banner("✅ Pipeline Completado", Colors.GREEN)
    ok_n = sum(1 for r in results if r.get("status") == "OK")
    print(f"  Tareas OK: {ok_n}/{len(results)}")
    print(f"  Rama: {branch}")
    print(f"  Logs: {LOGS_DIR}")
    print(f"\n{Colors.BOLD}Tu turno:{Colors.RESET} revisa la Draft PR, prueba en local, aprueba. ☕")
