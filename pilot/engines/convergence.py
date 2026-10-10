"""
Motor de Convergencia Multi-Barrido con Memoria Acumulativa y Cuadrantes Acotados.
Responsabilidad única: Orquestar el bucle de convergencia adversarial con delimitación de alcance
y memoria incremental hasta certificar 0 nuevos bugs.

Filosofía del Motor de Convergencia:
1. Delimitación de Alcance (Quadrant Chunking): Subdivide el objetivo en cuadrantes de ~250-400 líneas
   para prevenir sobrecarga cognitiva y alucinaciones por contexto desbordado.
2. Memoria Acumulativa (Cumulative Memory): Ingesta registros previos (ej: SEC-01 a SEC-21) e inyecta
   la lista de exclusión en cada prompt para obligar a los agentes a descubrir fallos no explorados.
3. Especialización Dual-Modelo:
   - Scanner (Flash High): barrido rápido, análisis profundo de flujo y generación de casos de prueba.
   - Verifier (Claude Sonnet): auditor adversarial estrictamente de solo-lectura (evalúa falsos positivos, cero código).
4. Criterio de Parada Certificado: Termina cuando se alcanza la racha limpia exigida o cuando se emite
   la señal canónica [CONVERGENCIA TOTAL ALCANZADA: 0 NUEVOS BUGS].
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pilot.config import get_logs_dir, resolve_model
from pilot.core.parser import extract_json
from pilot.core.runner import AgentRunner, default_runner
from pilot.core.scope import ScopeContract, ScopeDiscoveryEngine
from pilot.core.storage import log_run
from pilot.core.ui import Colors, Timer, banner, err, info, ok, step, warn



@dataclass
class Quadrant:
    id: str
    name: str
    files: list[Path] = field(default_factory=list)
    total_lines: int = 0
    file_snippets: dict[str, str] = field(default_factory=dict)


class CumulativeMemory:
    """Gestiona el registro de bugs conocidos a lo largo de múltiples barridos o sesiones previas."""

    def __init__(self, initial_bugs: list[dict] | None = None):
        self.bugs: list[dict] = list(initial_bugs or [])
        self._seen_signatures: set[str] = set()
        for b in self.bugs:
            sig = self._signature(b)
            self._seen_signatures.add(sig)

    @staticmethod
    def _signature(bug: dict) -> str:
        f = str(bug.get("archivo", "")).strip().lower()
        d = str(bug.get("descripcion", "")).strip().lower()[:40]
        return f"{f}|{d}"

    def add_bug(self, bug: dict) -> bool:
        """Añade un bug si no es duplicado. Retorna True si fue añadido."""
        sig = self._signature(bug)
        if sig in self._seen_signatures:
            return False
        if not bug.get("id"):
            bug["id"] = f"SEC-{len(self.bugs) + 1:02d}"
        self.bugs.append(bug)
        self._seen_signatures.add(sig)
        return True

    def count(self) -> int:
        return len(self.bugs)

    @classmethod
    def load_from_file(cls, path_str: str | Path | None) -> "CumulativeMemory":
        """Carga bugs documentados desde un archivo Markdown con tabla/secciones o desde JSON."""
        if not path_str:
            return cls([])

        path = Path(path_str).resolve()
        if not path.exists():
            warn(f"Archivo de memoria acumulada no encontrado: {path}")
            return cls([])

        text = path.read_text(encoding="utf-8", errors="replace")
        loaded_bugs = []

        # Intento 1: Archivo JSON
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    return cls(data)
                if isinstance(data, dict) and "hallazgos" in data:
                    return cls(data["hallazgos"])
            except Exception:
                pass

        # Intento 2: Tablas Markdown dinámicas con detección de cabeceras
        lines = [l.strip() for l in text.splitlines()]
        tables: list[list[str]] = []
        curr: list[str] = []
        for l in lines:
            if l.startswith("|") and l.endswith("|"):
                curr.append(l)
            else:
                if curr:
                    tables.append(curr)
                    curr = []
        if curr:
            tables.append(curr)

        for t in tables:
            if len(t) < 3:
                continue
            header = [c.strip().lower() for c in t[0].strip("|").split("|")]
            if not any("id" in h for h in header):
                continue

            id_idx = next((i for i, h in enumerate(header) if "id" in h), 0)
            file_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["archivo", "file", "ubicaci"])), -1)
            sev_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["severidad", "severity"]) or (h == "tipo" and not any("sever" in x for x in header))), -1)
            desc_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["descripci", "fallo", "detalle", "título", "titulo"]) or (h == "tipo" and any("sever" in x for x in header))), -1)
            dom_idx = next((i for i, h in enumerate(header) if any(k in h for k in ["dominio", "cuadrante", "subsistema"])), -1)

            for row in t[2:]:
                cols = [c.strip() for c in row.strip("|").split("|")]
                if len(cols) <= max(id_idx, file_idx if file_idx != -1 else 0):
                    continue
                raw_id = cols[id_idx].replace("*", "").strip()
                if not re.match(r"^[A-Z0-9_-]+$", raw_id, re.IGNORECASE) or raw_id.isdigit():
                    continue

                clean_file = cols[file_idx].replace("`", "").strip() if file_idx != -1 and file_idx < len(cols) else ""
                clean_sev = cols[sev_idx].replace("`", "").replace("*", "").strip().upper() if sev_idx != -1 and sev_idx < len(cols) else "ALTA"
                clean_desc = cols[desc_idx].replace("`", "").strip() if desc_idx != -1 and desc_idx < len(cols) else ""
                clean_dom = cols[dom_idx].replace("`", "").strip() if dom_idx != -1 and dom_idx < len(cols) else ""

                loaded_bugs.append({
                    "id": raw_id,
                    "archivo": clean_file,
                    "severidad": clean_sev,
                    "descripcion": clean_desc,
                    "dominio": clean_dom,
                })

        # Intento 3: Secciones Markdown: ### SEC-01: Título ... - **Ubicación:** `archivo`
        if not loaded_bugs:
            section_pattern = re.compile(
                r"###\s*\*\*?([A-Z0-9_-]+)\*\*?:\s*([^\n]+)([\s\S]*?)(?=###|$)"
            )
            for m in section_pattern.finditer(text):
                bug_id = m.group(1).strip()
                title = m.group(2).strip()
                body = m.group(3)
                loc_m = re.search(r"Ubicaci[oó]n:\s*`?([^`\n]+)`?", body, re.IGNORECASE)
                sev_m = re.search(r"Severidad:\s*([A-Za-z0-9_-]+)", body, re.IGNORECASE)
                loaded_bugs.append({
                    "id": bug_id,
                    "descripcion": title,
                    "archivo": loc_m.group(1).strip() if loc_m else "",
                    "severidad": sev_m.group(1).strip().upper() if sev_m else "ALTA",
                })

        ok(f"Memoria Acumulativa cargada: {len(loaded_bugs)} bugs preexistentes desde '{path.name}'")
        return cls(loaded_bugs)

    def to_prompt_context(self, max_items: int = 50, max_chars: int = 4000) -> str:
        """Formatea los bugs conocidos en un bloque conciso de exclusión para el prompt."""
        if not self.bugs:
            return "Ningún bug registrado previamente en memoria."

        lines = [f"YA EXISTE un registro exhaustivo de {len(self.bugs)} bugs documentados. NO REPITAS NINGUNO:"]
        total_len = 0
        for b in self.bugs[:max_items]:
            b_id = b.get("id", "?")
            f = b.get("archivo", "")
            d = b.get("descripcion", "")[:70]
            sev = b.get("severidad", "ALTA")
            entry = f"- [{b_id}] ({sev}) {f}: {d}"
            if total_len + len(entry) > max_chars:
                lines.append(f"... (+ {len(self.bugs) - len(lines) + 1} bugs adicionales omitidos por brevedad)")
                break
            lines.append(entry)
            total_len += len(entry)

        return "\n".join(lines)


def partition_into_quadrants(
    repo_path: Path,
    files: list[Path],
    max_lines_per_quadrant: int = 350,
) -> list[Quadrant]:
    """
    Subdivide los archivos objetivo en cuadrantes acotados por presupuesto de líneas
    para evitar saturación de contexto y cognitive overload en los subagentes.
    """
    file_info = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            lines = content.count("\n") + 1
            rel = str(f.relative_to(repo_path))
            file_info.append({"path": f, "rel": rel, "lines": lines, "content": content})
        except (OSError, ValueError):
            continue

    quadrants: list[Quadrant] = []
    current_q_files: list[Path] = []
    current_q_snippets: dict[str, str] = {}
    current_lines = 0
    q_index = 1

    for item in file_info:
        # Si un archivo individual supera el umbral, va en su propio cuadrante exclusivo
        if item["lines"] >= max_lines_per_quadrant:
            if current_q_files:
                q_name = f"Quadrant-{q_index:02d} ({len(current_q_files)} archivos, {current_lines} líneas)"
                quadrants.append(Quadrant(
                    id=f"Q{q_index:02d}",
                    name=q_name,
                    files=current_q_files,
                    total_lines=current_lines,
                    file_snippets=current_q_snippets,
                ))
                q_index += 1
                current_q_files = []
                current_q_snippets = {}
                current_lines = 0

            # Cuadrante exclusivo para el archivo grande
            quadrants.append(Quadrant(
                id=f"Q{q_index:02d}",
                name=f"Quadrant-{q_index:02d}-Solo: {Path(item['rel']).name} ({item['lines']} líneas)",
                files=[item["path"]],
                total_lines=item["lines"],
                file_snippets={item["rel"]: item["content"]},
            ))
            q_index += 1
            continue

        # Si agregar el archivo excede el presupuesto del cuadrante actual, cerrar y abrir uno nuevo
        if current_lines + item["lines"] > max_lines_per_quadrant and current_q_files:
            q_name = f"Quadrant-{q_index:02d} ({len(current_q_files)} archivos, {current_lines} líneas)"
            quadrants.append(Quadrant(
                id=f"Q{q_index:02d}",
                name=q_name,
                files=current_q_files,
                total_lines=current_lines,
                file_snippets=current_q_snippets,
            ))
            q_index += 1
            current_q_files = []
            current_q_snippets = {}
            current_lines = 0

        current_q_files.append(item["path"])
        current_q_snippets[item["rel"]] = item["content"]
        current_lines += item["lines"]

    # Agregar cuadrante remanente
    if current_q_files:
        q_name = f"Quadrant-{q_index:02d} ({len(current_q_files)} archivos, {current_lines} líneas)"
        quadrants.append(Quadrant(
            id=f"Q{q_index:02d}",
            name=q_name,
            files=current_q_files,
            total_lines=current_lines,
            file_snippets=current_q_snippets,
        ))

    return quadrants


def run_convergence_loop(
    repo: str,
    filter_keyword: str = "",
    seed_files: list[str] | None = None,
    memory_file: str | None = None,
    scanner_model: str = "flash",
    verifier_model: str = "claude",
    max_lines_per_quadrant: int = 350,
    max_cycles: int = 5,
    clean_streak_target: int = 1,
    output_report: str | None = None,
    max_depth: int = 2,
    include_shared_tables: bool = True,
    runner: AgentRunner | None = None,
) -> dict[str, Any]:
    """
    Ejecuta el bucle de convergencia multi-barrido:
    - Mapeo de alcance inteligente (Scope Discovery Engine) trazando el hilo entre módulos
    - Escaneo por cuadrantes acotados (Flash)
    - Verificación adversarial fiscal (Claude)
    - Inyección acumulativa de bugs previos (Anti-Repetición)
    - Certificación formal de convergencia
    """
    banner("MOTOR DE CONVERGENCIA MULTI-BARRIDO (agy-pilot v3)", Colors.CYAN)
    active_runner = runner or default_runner
    repo_path = Path(repo).resolve()

    resolved_scanner = resolve_model(scanner_model)
    resolved_verifier = resolve_model(verifier_model)

    info(f"Repositorio: {repo_path}")
    info(f"Filtro / Semillas: '{filter_keyword or (', '.join(seed_files) if seed_files else 'TODOS')}'")
    info(f"Scanner (detección profunda): {resolved_scanner}")
    info(f"Verifier (auditoría fiscal solo lectura): {resolved_verifier}")
    info(f"Líneas máx por cuadrante: {max_lines_per_quadrant}")
    info(f"Ciclos máx: {max_cycles} | Racha limpia para certificar: {clean_streak_target}")

    # 1. Cargar memoria previa
    memory = CumulativeMemory.load_from_file(memory_file)
    initial_known_count = memory.count()

    # 2. Descubrir alcance trazando el hilo (Scope Discovery Engine)
    scope_engine = ScopeDiscoveryEngine(repo_path)
    skip_dirs = {"node_modules", ".git", "__pycache__", "dist", "build", ".next", "venv", ".venv"}
    keywords = [k.strip().lower() for k in filter_keyword.split(",") if k.strip()] if filter_keyword else []

    seeds: list[Path] = []
    if seed_files:
        for s in seed_files:
            sp = (repo_path / s).resolve() if not Path(s).is_absolute() else Path(s).resolve()
            if sp.exists():
                seeds.append(sp)
        if not seeds:
            warn(f"Ninguna de las semillas especificadas existe.")
            return {"convergencia_alcanzada": False, "nuevos_bugs": [], "total_bugs": memory.count()}
    elif keywords:
        for ext in ["ts", "tsx", "js", "jsx", "py"]:
            for f in repo_path.rglob(f"*.{ext}"):
                if not any(part in skip_dirs for part in f.parts) and f.is_file():
                    rel_str = str(f.relative_to(repo_path)).lower()
                    if any(kw in rel_str for kw in keywords):
                        seeds.append(f)

    if seeds:
        info(f"[SCOPE] Tirando del hilo desde {len(seeds)} semilla(s) de entrada...")
        contract = scope_engine.discover_scope(seeds, max_depth=max_depth, include_shared_tables=include_shared_tables)
        target_files = contract.target_files
        ok(f"[SCOPE] Grafo de impacto trazado: {len(target_files)} archivos interconectados.")
        if contract.shared_tables:
            info(f"[SCOPE] Tablas compartidas vinculadas: {', '.join(sorted(contract.shared_tables))}")
        if contract.external_perimeters:
            info(f"[SCOPE] Fronteras externas detectadas: {', '.join(sorted(contract.external_perimeters))}")
    else:
        target_files = []
        for ext in ["ts", "tsx", "js", "jsx", "py"]:
            for f in repo_path.rglob(f"*.{ext}"):
                if not any(part in skip_dirs for part in f.parts) and f.is_file():
                    target_files.append(f)
        contract = ScopeContract(seeds=[], target_files=target_files, relative_files=[str(f.relative_to(repo_path)) for f in target_files])

    if not target_files:
        warn(f"No se encontraron archivos en el alcance para {repo_path}")
        return {"convergencia_alcanzada": False, "nuevos_bugs": [], "total_bugs": memory.count()}

    # 3. Particionar en cuadrantes acotados
    quadrants = partition_into_quadrants(repo_path, target_files, max_lines_per_quadrant=max_lines_per_quadrant)
    ok(f"Alcance delimitado en {len(quadrants)} cuadrante(s) a partir de {len(target_files)} archivo(s).")
    for q in quadrants:
        info(f"  • [{q.id}] {q.name}")
    print()


    newly_discovered_bugs: list[dict] = []
    clean_streak = 0
    convergence_reached = False

    for cycle in range(1, max_cycles + 1):
        banner(f"BARRIDO DE CONVERGENCIA {cycle}/{max_cycles}  |  Racha limpia: {clean_streak}/{clean_streak_target}", Colors.YELLOW)
        cycle_new_bugs = 0

        for q in quadrants:
            step_title = f"Analizando {q.id}: {q.name}"
            step(cycle, step_title)

            # Construir código del cuadrante
            code_parts = []
            for rel, snippet in q.file_snippets.items():
                code_parts.append(f"### Archivo: `{rel}`\n```\n{snippet}\n```\n")
            quadrant_code = "\n".join(code_parts)

            memory_context = memory.to_prompt_context()

            scan_prompt = f"""# ROL: Ingeniero de Calidad de Software — Revisión Estructural en Sandbox

## CUADRANTE OBJETIVO: {q.name}
{quadrant_code}

## MEMORIA ACUMULATIVA — BUGS YA DOCUMENTADOS
{memory_context}

## MISIÓN CRÍTICA
1. Examina exhaustivamente el código del cuadrante.
2. NO REPITAS ningún bug ya registrado en la memoria acumulativa.
3. Todo hallazgo DEBE incluir:
   - Archivo exacto y línea aproximada.
   - Descripción concreta de la falla (hecho empírico).
   - Caso de prueba reproducible (`input -> comportamiento incorrecto observable`).
   - ESTÁ ESTRICTAMENTE PROHIBIDO CALIFICAR LA SEVERIDAD O IMPACTO.
4. Si NO existen vulnerabilidades nuevas en este cuadrante, responde EXACTAMENTE:
   [CONVERGENCIA TOTAL ALCANZADA: 0 NUEVOS BUGS]

## FORMATO DE RESPUESTA (ÚNICAMENTE JSON)
```json
{{
  "hallazgos": [
    {{
      "archivo": "ruta/al/archivo.ts",
      "linea_aprox": 42,
      "descripcion": "Descripción del fallo",
      "caso_de_prueba": "input -> comportamiento incorrecto observable"
    }}
  ]
}}
```"""

            info(f"  [SCANNER] Flash analizando {q.id}...")
            with Timer(f"scanner_{q.id}"):
                _, scan_out = active_runner.run(scan_prompt, repo, new_project=True, model=resolved_scanner)

            log_run(f"converge_c{cycle}_{q.id}_scan", scan_out or "(sin output)")

            # Verificar si se emitió señal de convergencia limpia
            if not scan_out or "[CONVERGENCIA TOTAL ALCANZADA" in scan_out or "REPO_LIMPIO" in scan_out or "QUADRANT_LIMPIO" in scan_out:
                ok(f"  ✓ {q.id} LIMPIO: Sin nuevos bugs detectados.")
                continue

            try:
                parsed_scan = extract_json(scan_out, context=f"converge_c{cycle}_{q.id}")
                if isinstance(parsed_scan, dict):
                    if parsed_scan.get("convergencia_alcanzada"):
                        ok(f"  ✓ {q.id} LIMPIO (Convergencia canónica).")
                        continue
                    candidates = parsed_scan.get("hallazgos", [])
                elif isinstance(parsed_scan, list):
                    candidates = parsed_scan
                else:
                    candidates = []
            except ValueError:
                warn(f"  ⚠ JSON irregular en {q.id}. Tratando como candidato libre.")
                candidates = [{"archivo": q.files[0].name, "descripcion": scan_out[:250], "caso_de_prueba": "Ver log"}]

            if not candidates:
                ok(f"  ✓ {q.id} LIMPIO.")
                continue

            # ── PASO 2: VERIFIER (Claude) — Evaluación adversarial solo lectura ─────
            info(f"  [VERIFIER] Claude verificando {len(candidates)} candidato(s) en {q.id}...")
            verify_prompt = f"""# ROL: Revisor de Calidad de Código — Evaluación de Defectos (CERO CÓDIGO)

Evalúa estos candidatos reportados en `{q.name}` frente al código:

## CANDIDATOS:
{json.dumps(candidates, ensure_ascii=False, indent=2)}

## CÓDIGO DEL CUADRANTE:
{quadrant_code}

## REGLAS FISCALES:
1. SOLO evalúa si el bug es REAL o FALSO POSITIVO. NO escribas código ni sugerencias.
2. Un bug es REAL únicamente si el caso de prueba rompe el código de forma reproducible.
3. Si el bug ya corresponde a la memoria conocida o es una alucinación teórica, márcalo como falso positivo.

## RESPUESTA (JSON estricto):
```json
{{
  "verificados": [
    {{
      "candidato_index": 0,
      "es_real": true,
      "razon_fiscal": "Explicación en una línea de por qué rompe"
    }}
  ]
}}
```"""

            with Timer(f"verifier_{q.id}"):
                v_code, verify_out = active_runner.run(verify_prompt, repo, new_project=True, model=resolved_verifier)

            # Detección de agotamiento de tokens / cuota con failover automático a Gemini Pro
            if (v_code != 0 or not verify_out or "quota" in (verify_out or "").lower() or "exhausted" in (verify_out or "").lower()) and "claude" in resolved_verifier.lower():
                warn(f"  ⚠ Cuota agotada o error en {resolved_verifier}. Activando failover automático a Gemini Pro ('pro')...")
                fallback_verifier = resolve_model("pro")
                with Timer(f"verifier_fallback_{q.id}"):
                    v_code, verify_out = active_runner.run(verify_prompt, repo, new_project=True, model=fallback_verifier)

            log_run(f"converge_c{cycle}_{q.id}_verify", verify_out or "(sin output)")

            try:
                parsed_verify = extract_json(verify_out, context=f"verify_c{cycle}_{q.id}")
                if isinstance(parsed_verify, dict):
                    verified_list = parsed_verify.get("verificados", [])
                elif isinstance(parsed_verify, list):
                    verified_list = parsed_verify
                else:
                    verified_list = []
                confirmed = [v for v in verified_list if isinstance(v, dict) and v.get("es_real")]
            except ValueError:
                warn(f"  ⚠ JSON irregular en Verifier {q.id}. Se descartan candidatos no verificables.")
                confirmed = []

            if not confirmed:
                ok(f"  ✓ {q.id}: Todos los candidatos fueron descartados como falsos positivos.")
                continue

            # Extraer candidatos confirmados reales
            real_candidates = []
            for c in confirmed:
                idx = c.get("candidato_index", 0)
                if 0 <= idx < len(candidates):
                    cand = candidates[idx]
                    cand["razon_fiscal"] = c.get("razon_fiscal", "")
                    cand["cuadrante"] = q.id
                    cand["ciclo"] = cycle
                    real_candidates.append(cand)

            if not real_candidates:
                continue

            # Integrar bugs a la memoria en crudo (Severidad PENDIENTE)
            for cand in real_candidates:
                cand["severidad"] = "PENDIENTE_KEV"
                cand["dominio_asignado"] = "PENDIENTE_KEV"
                
                if memory.add_bug(cand):
                    cycle_new_bugs += 1
                    newly_discovered_bugs.append(cand)
                    sev_color = Colors.CYAN
                    print(f"    {sev_color}[{cand['id']}][PENDIENTE]{Colors.RESET} {cand.get('archivo')} — {cand.get('descripcion')[:65]}")

        # Evaluación de fin de ciclo
        if cycle_new_bugs == 0:
            clean_streak += 1
            ok(f"Ciclo {cycle} completado con CERO nuevos bugs. Racha limpia: {clean_streak}/{clean_streak_target}")
            if clean_streak >= clean_streak_target:
                convergence_reached = True
                banner("🎉 CONVERGENCIA TOTAL CERTIFICADA (0 NUEVOS BUGS) 🎉", Colors.GREEN)
                break
        else:
            clean_streak = 0
            warn(f"Ciclo {cycle}: {cycle_new_bugs} nuevo(s) bug(s) documentado(s). Continuando bucle...")

    # 4. Generación del Informe Consolidado
    banner("GENERACIÓN DE INFORME DE CONVERGENCIA", Colors.CYAN)
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_lines = [
        f"# Informe de Certificación de Convergencia — {repo_path.name}",
        f"\n**Fecha:** {ts_str}  ",
        f"**Estado de Convergencia:** {'CERTIFICADA (0 Nuevos Bugs)' if convergence_reached else 'LÍMITE DE CICLOS ALCANZADO'}  ",
        f"**Bugs Preexistentes Ingestados:** {initial_known_count}  ",
        f"**Nuevos Bugs Descubiertos:** {len(newly_discovered_bugs)}  ",
        f"**Total Bugs en Memoria Acumulada:** {memory.count()}  \n",
        "## Matriz Consolidada de Vulnerabilidades\n",
        "| ID | Dominio / Cuadrante | Severidad | Archivo | Descripción |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for b in memory.bugs:
        b_id = str(b.get("id", "SEC-?")).replace("|", "&#124;")
        dom = str(b.get("cuadrante", b.get("dominio", "General"))).replace("|", "&#124;")
        sev = str(b.get("severidad", "MEDIA")).replace("|", "&#124;")
        f = str(b.get("archivo", "?")).replace("|", "&#124;")
        desc = str(b.get("descripcion", "")).replace("\n", " ").replace("|", "&#124;")
        report_lines.append(f"| **{b_id}** | {dom} | {sev} | `{f}` | {desc} |")

    report_content = "\n".join(report_lines) + "\n"

    target_report_path = Path(output_report) if output_report else get_logs_dir() / f"CONVERGENCE_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    try:
        target_report_path.parent.mkdir(parents=True, exist_ok=True)
        target_report_path.write_text(report_content, encoding="utf-8")
        ok(f"Informe guardado en: {target_report_path}")
    except OSError as e:
        warn(f"No se pudo escribir en {target_report_path}: {e}")

    return {
        "convergencia_alcanzada": convergence_reached,
        "nuevos_bugs": newly_discovered_bugs,
        "total_bugs": memory.count(),
        "report_path": str(target_report_path),
    }
