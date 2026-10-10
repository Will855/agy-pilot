"""
Motor de auditoría continua dual-modelo (sweep).
Responsabilidad única: Barrido completo del repositorio hasta alcanzar estabilidad (cero bugs confirmados).
Arquitectura dual-modelo:
  - Scanner (ej: Flash High): Escaneo amplio del repo + aplicación de fixes mínimos.
  - Verifier (ej: Claude Sonnet): Verificación de falsos positivos (CERO código, solo evaluación).
"""

import json
from collections import Counter
from pathlib import Path

from pilot.config import resolve_model
from pilot.core.git import GitClient
from pilot.core.parser import extract_json
from pilot.core.runner import AgentRunner, default_runner
from pilot.core.storage import log_run
from pilot.core.ui import Colors, Timer, banner, info, ok, warn

def continuous_sweep(
    repo: str,
    scanner_model: str,
    verifier_model: str,
    extensions: list[str],
    max_cycles: int = 10,
    clean_cycles_to_stop: int = 2,
    filter_keyword: str = "",
    runner: AgentRunner | None = None,
) -> list[dict]:
    banner("MODO SWEEP — Auditoría Continua Dual-Modelo", Colors.YELLOW)
    info(f"Scanner (escaneo + fixes): {scanner_model}")
    info(f"Verifier (solo verificación, sin código): {verifier_model}")
    info(f"Extensiones objetivo: {', '.join(extensions)}")
    if filter_keyword:
        info(f"Filtro de archivos: {filter_keyword}")
    info(f"Ciclos máximos: {max_cycles} | Ciclos limpios para parar: {clean_cycles_to_stop}")
    print()

    active_runner = runner or default_runner
    git_client = GitClient(repo)
    repo_path = Path(repo)

    skip_dirs = {"node_modules", ".git", "__pycache__", "dist", "build", ".next", "venv", ".venv"}
    all_files = []
    keywords = [k.strip().lower() for k in filter_keyword.split(",") if k.strip()] if filter_keyword else []

    for ext in extensions:
        for f in repo_path.rglob(f"*.{ext.lstrip('.')}"):
            if not any(part in skip_dirs for part in f.parts) and f.is_file():
                if keywords:
                    rel_str = str(f.relative_to(repo_path)).lower()
                    if not any(kw in rel_str for kw in keywords):
                        continue
                all_files.append(f)

    if not all_files:
        warn(f"No se encontraron archivos con extensiones {extensions} (filtro: '{filter_keyword}') en {repo}")
        return []
    info(f"Archivos a auditar: {len(all_files)}")


    all_confirmed_bugs: list[dict] = []
    clean_streak = 0

    for cycle in range(1, max_cycles + 1):
        banner(f"CICLO {cycle}/{max_cycles}  |  Ciclos limpios: {clean_streak}/{clean_cycles_to_stop}", Colors.YELLOW)

        # ── PASO 1: SCANNER (Flash) escanea el repositorio completo ────────────
        info("[SCANNER] Construyendo mapa del repo para Flash High...")
        file_map_parts = []
        total_chars = 0
        char_budget = 34000
        for f in all_files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(f.relative_to(repo_path))
            snippet = f"\n### {rel}\n```\n{content[:2500]}\n```"
            if total_chars + len(snippet) > char_budget:
                file_map_parts.append("\n[... más archivos omitidos por límite de contexto ...]")
                break
            file_map_parts.append(snippet)
            total_chars += len(snippet)
        file_map = "".join(file_map_parts)

        already_known = json.dumps(
            [{"a": b.get("archivo") or "", "d": (b.get("descripcion") or "")[:60]} for b in all_confirmed_bugs],
            ensure_ascii=False
        )[:1500] if all_confirmed_bugs else "Ninguno."

        scan_prompt = f"""# ROL: Cazador de Vulnerabilidades — Escaneo Completo del Repositorio

## REPOSITORIO
{file_map}

## YA CONOCIDOS — NO repetir
{already_known}

## MISIÓN
Busca ÚNICAMENTE hallazgos concretos con caso de prueba reproducible:
- Vulnerabilidades de seguridad (bypass auth, price tampering, race conditions, inyecciones, path traversal)
- Bugs de producción (null no manejado, tipo incorrecto, estado inconsistente)
- Errores silenciosos (excepciones ignoradas, promesas sin .catch)

Por cada hallazgo DEBES incluir: input exacto → comportamiento incorrecto observable.
Sin caso de prueba concreto = no lo reportes.
Si no hay nada nuevo, responde EXACTAMENTE: REPO_LIMPIO

## FORMATO
```json
{{"hallazgos": [{{"archivo": "ruta/archivo.ts", "linea_aprox": 42, "categoria": "seguridad|bug|silencioso", "descripcion": "que esta mal", "caso_de_prueba": "input a fallo"}}]}}
```"""

        info("[SCANNER] Enviando a Flash High...")
        with Timer("scanner"):
            _, scan_output = active_runner.run(scan_prompt, repo, new_project=True, model=scanner_model)
        log_run(f"sweep_c{cycle}_scan", scan_output or "(sin output)")

        if not scan_output or "REPO_LIMPIO" in scan_output:
            info("[SCANNER] Flash no encontró candidatos nuevos.")
            clean_streak += 1
            if clean_streak >= clean_cycles_to_stop:
                ok(f"Criterio de parada alcanzado: {clean_streak} ciclos limpios.")
                break
            continue

        try:
            scan_data = extract_json(scan_output, context=f"sweep_scan_c{cycle}")
            candidatos = scan_data.get("hallazgos", []) if isinstance(scan_data, dict) else []
        except ValueError:
            warn("[SCANNER] JSON inválido — usando texto libre como candidato único")
            candidatos = [{"archivo": "desconocido", "descripcion": scan_output[:300], "caso_de_prueba": "ver log"}]

        if not candidatos:
            clean_streak += 1
            if clean_streak >= clean_cycles_to_stop:
                ok(f"Criterio de parada alcanzado: {clean_streak} ciclos limpios.")
                break
            continue

        ok(f"[SCANNER] {len(candidatos)} candidato(s). Enviando a Claude para verificación...")

        # ── PASO 2: VERIFIER (Claude) — solo confirma, cero código ──────────────
        verify_prompt = f"""# ROL: Fiscal de Bugs — SOLO análisis, CERO código

Tienes {len(candidatos)} hallazgo(s). Determina cuáles son bugs REALES vs falsos positivos.

## HALLAZGOS
{json.dumps(candidatos, ensure_ascii=False, indent=2)[:5000]}

## REGLAS
- NO escribas código. NO sugieras fixes. SOLO verifica.
- Un bug es real si el caso de prueba es concreto y el código confirma el fallo.
- Respuesta breve: una línea de razón por hallazgo.

## RESPUESTA (JSON, sin texto adicional)
```json
{{"verificados": [{{"hallazgo_index": 0, "es_real": true, "severidad": "critica|alta|media|baja", "razon": "una línea"}}]}}
```"""

        info("[VERIFIER] Enviando a Claude Sonnet (solo verificación)...")
        with Timer("verifier"):
            v_code, verify_output = active_runner.run(verify_prompt, repo, new_project=True, model=verifier_model)

        # Detección de agotamiento de tokens / cuota con failover automático a Gemini Pro
        if (v_code != 0 or not verify_output or "quota" in (verify_output or "").lower() or "exhausted" in (verify_output or "").lower()) and "claude" in verifier_model.lower():
            warn("⚠ Cuota agotada o error en Claude. Activando failover automático a Gemini Pro ('pro')...")
            fallback_verifier = resolve_model("pro")
            with Timer("verifier_fallback"):
                v_code, verify_output = active_runner.run(verify_prompt, repo, new_project=True, model=fallback_verifier)

        log_run(f"sweep_c{cycle}_verify", verify_output or "(sin output)")

        try:
            verify_data = extract_json(verify_output, context=f"sweep_verify_c{cycle}")
            verificados = verify_data.get("verificados", []) if isinstance(verify_data, dict) else []
            reales = [v for v in verificados if v.get("es_real")]
        except ValueError:
            warn("[VERIFIER] JSON inválido — conservando candidatos sin filtrar")
            reales = [{"hallazgo_index": i, "es_real": True, "severidad": "media", "razon": "sin verificación"} for i in range(len(candidatos))]

        if not reales:
            ok("[VERIFIER] Claude: 0 bugs reales confirmados en este ciclo.")
            clean_streak += 1
            if clean_streak >= clean_cycles_to_stop:
                ok(f"Criterio de parada alcanzado: {clean_streak} ciclos limpios.")
                break
            continue

        clean_streak = 0
        cycle_confirmed = []
        ok(f"[VERIFIER] {len(reales)} bug(s) real(es):")
        for v in reales:
            try:
                idx_val = v.get("hallazgo_index")
                idx = int(idx_val) if idx_val is not None else 0
            except (ValueError, TypeError):
                idx = -1

            if 0 <= idx < len(candidatos):
                sev = v.get("severidad") or "?"
                bug = {**candidatos[idx], "severidad": sev, "razon_fiscal": v.get("razon") or ""}
                cycle_confirmed.append(bug)
                all_confirmed_bugs.append(bug)
                color = Colors.RED if sev == "critica" else Colors.YELLOW
                desc = (bug.get("descripcion") or "")[:65]
                arch = bug.get("archivo") or "?"
                print(f"  {color}[{sev.upper()}]{Colors.RESET} {arch} — {desc}")

        # ── PASO 3: SCANNER (Flash) implementa los fixes ─────────────────────────
        banner(f"CICLO {cycle} — Aplicando fixes con Flash High", Colors.CYAN)
        fixed_files = []
        for bug in cycle_confirmed:
            archivo = bug.get("archivo", "")
            fix_path = repo_path / archivo
            if not fix_path.exists():
                warn(f"  Archivo no encontrado: {archivo}")
                continue
            try:
                snippet = fix_path.read_text(encoding="utf-8", errors="replace")[:5500]
            except OSError:
                snippet = "(no legible)"

            fix_prompt = f"""# ROL: Implementador de Fix — un bug, una corrección mínima

## BUG CONFIRMADO
Archivo: `{archivo}`
Descripción: {bug.get('descripcion', '')}
Caso de prueba: {bug.get('caso_de_prueba', '')}
Severidad: {bug.get('severidad', '?')}

## CÓDIGO ACTUAL
```
{snippet}
```

## REGLAS
1. Modifica SOLO `{archivo}`
2. Cambio mínimo — no reformatees ni renombres nada fuera del bug
3. El fix debe eliminar la condición que causa el bug
4. Al terminar escribe: FIX_COMPLETO"""

            info(f"  [SCANNER] Fix en {archivo}...")
            with Timer("fix"):
                _, fix_out = active_runner.run(fix_prompt, repo, new_project=True, model=scanner_model)
            log_run(f"sweep_c{cycle}_fix_{Path(archivo).stem}", fix_out or "(sin output)")

            if fix_out and "FIX_COMPLETO" in fix_out:
                ok(f"  ✓ {archivo}")
                fixed_files.append(archivo)
            else:
                warn(f"  ⚠ Fix incierto en {archivo} — revisa el log")

        if fixed_files and git_client.is_valid_repo():
            msg = f"sweep(c{cycle}): fix {len(fixed_files)} bug(s) auditados"
            git_client.commit(msg)
            ok(f"Commit: {msg}")

    # ── REPORTE FINAL ─────────────────────────────────────────────────────────────
    banner("SWEEP COMPLETADO", Colors.GREEN)
    report = log_run("sweep_final", json.dumps(all_confirmed_bugs, ensure_ascii=False, indent=2))
    ok(f"Total bugs corregidos: {len(all_confirmed_bugs)}")
    ok(f"Reporte: {report}")
    if not all_confirmed_bugs:
        ok("Repositorio limpio — ningún bug confirmado en toda la ejecución. ✅")
    else:
        sevs = Counter(b.get("severidad", "?") for b in all_confirmed_bugs)
        print(f"\n{Colors.BOLD}Distribución por severidad:{Colors.RESET}")
        for sev in ["critica", "alta", "media", "baja"]:
            if sevs.get(sev):
                print(f"  {sev.upper()}: {sevs[sev]}")

    return all_confirmed_bugs
