"""
Punto de entrada de línea de comandos (CLI) de agy-pilot.
Responsabilidad única: Parseo de argumentos y despacho a los motores correspondientes.
"""

import argparse
import sys
import json
from pathlib import Path

from pilot.config import get_default_model, resolve_model
from pilot.core.git import GitClient
from pilot.core.runner import AgyRunner
from pilot.core.storage import check_system_prerequisites
from pilot.core.ui import Colors, banner, err, info, ok
from pilot.engines.branch_review import audit_branch
from pilot.engines.convergence import run_convergence_loop
from pilot.engines.deep_audit import deep_audit_loop
from pilot.engines.doctor import run_doctor
from pilot.engines.pipeline import execute_pipeline
from pilot.engines.self_test import run_self_test
from pilot.engines.sweep import continuous_sweep
from pilot.engines.surgery import SurgeryEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="agy-pilot v3 — Orquestador de desarrollo asistido por IA (Modular & SOLID)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Diagnóstico del entorno:
  agy-pilot doctor

  # Auditar cambios de la rama actual vs main:
  agy-pilot review

  # Auditoría profunda de un archivo (bucle de agotamiento):
  agy-pilot audit --file src/payments/processor.ts

  # Auditoría continua dual-modelo en todo el repo:
  agy-pilot sweep --repo . --scanner flash --verifier claude

  # Bucle de convergencia con cuadrantes acotados y memoria acumulada:
  agy-pilot converge --repo . --filter "checkout,payment" --memory-file docs/reports/INFORME.md

  # Pipeline completo ticket → PR:
  agy-pilot run --ticket "Implementar validación de tarjeta"
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # test: auto-auditoría de agy-pilot
    sub.add_parser("test", help="Ejecuta la suite de auto-auditoría y verificación de contratos de agy-pilot")

    # doctor
    d = sub.add_parser("doctor", help="Verifica el entorno antes de ejecutar un pipeline")
    d.add_argument("--repo", default=".", help="Ruta al repo para probar agy (default: .)")
    d.add_argument("--model", default=None, help="Modelo o alias a probar (ej: flash, pro, claude)")


    # review
    r = sub.add_parser("review", help="Audita el diff de la rama actual vs la base")
    r.add_argument("--repo", default=".", help="Ruta al repo (default: .)")
    r.add_argument("--base", default="main", help="Rama base de comparación (default: main)")
    r.add_argument("--ticket", default="", help="Contexto opcional de lo que hace la rama")
    r.add_argument("--model", default=None, help="Modelo o alias a usar (ej: flash, pro, claude)")

    # audit
    a = sub.add_parser("audit", help="Auditoría profunda de un archivo (bucle de agotamiento)")
    a.add_argument("--repo", default=".", help="Ruta al repo (default: .)")
    a.add_argument("--file", required=True, help="Ruta relativa al archivo a auditar")
    a.add_argument("--rounds", type=int, default=5, help="Máximo de rondas (default: 5)")
    a.add_argument("--model", default=None, help="Modelo o alias a usar (ej: flash, pro, claude)")

    # sweep
    sw = sub.add_parser("sweep", help="Auditoría continua: Flash escanea+fixa, Claude solo verifica")
    sw.add_argument("--repo", default=".", help="Ruta al repo (default: .)")
    sw.add_argument("--scanner", default="flash", help="Modelo para escanear y aplicar fixes (default: flash)")
    sw.add_argument("--verifier", default="claude", help="Modelo para verificar hallazgos — solo lee (default: claude)")
    sw.add_argument("--ext", default="ts,py,js,tsx", help="Extensiones a auditar separadas por coma (default: ts,py,js,tsx)")
    sw.add_argument("--filter", default="", help="Subcadena para filtrar archivos (ej: checkout, payment)")
    sw.add_argument("--cycles", type=int, default=10, help="Ciclos máximos (default: 10)")
    sw.add_argument("--clean-streak", type=int, default=2, help="Ciclos limpios consecutivos para declarar fin (default: 2)")

    # converge
    cv = sub.add_parser("converge", help="Motor de convergencia multi-barrido con delimitación de alcance inteligente y memoria acumulativa")
    cv.add_argument("--repo", default=".", help="Ruta al repo (default: .)")
    cv.add_argument("--seed", default="", help="Rutas semilla separadas por coma para tirar del hilo (ej: src/app/api/checkout/route.ts)")
    cv.add_argument("--filter", default="", help="Subcadena para filtrar archivos (ej: checkout, payment, stripe)")
    cv.add_argument("--memory-file", default=None, help="Ruta al informe previo o JSON con bugs conocidos para evitar repeticiones")
    cv.add_argument("--scanner", default="flash", help="Modelo para escaneo profundo (default: flash)")
    cv.add_argument("--verifier", default="claude", help="Modelo para evaluación fiscal de solo lectura (default: claude)")
    cv.add_argument("--quadrant-lines", type=int, default=350, help="Límite aproximado de líneas por cuadrante (default: 350)")
    cv.add_argument("--cycles", type=int, default=5, help="Ciclos máximos de barrido (default: 5)")
    cv.add_argument("--clean-streak", type=int, default=1, help="Ciclos limpios completos para certificar convergencia (default: 1)")
    cv.add_argument("--output-report", default=None, help="Ruta personalizada para guardar el reporte final")
    cv.add_argument("--max-depth", type=int, default=2, help="Profundidad máxima de importaciones (default: 2)")
    cv.add_argument("--no-tables", action="store_true", help="No incluir archivos vinculados por tablas compartidas")

    # triage
    tr = sub.add_parser("triage", help="Triage manual de bugs registrados (Kev 4B)")
    tr.add_argument("--file", required=True, help="Ruta al archivo Markdown/JSON con los bugs a procesar")
    tr.add_argument("--chunk-start", type=int, default=0, help="Índice inicial del bloque")
    tr.add_argument("--chunk-size", type=int, default=None, help="Cantidad de bugs en el bloque")
    tr.add_argument("--repo", default=None, help="Ruta al repositorio para adjuntar el código a Kev")
    # surgery
    sg = sub.add_parser("surgery", help="Cirugía quirúrgica en lotes y arbitraje (Fase 2)")
    sg.add_argument("--repo", default=".", help="Ruta al repo (default: .)")
    sg.add_argument("--file", required=True, help="Ruta al archivo de Triage con bugs a operar")
    sg.add_argument("--surgeon", default="pro", help="Modelo para inyectar parches masivos (default: pro)")
    sg.add_argument("--auditor", default="claude", help="Modelo auditor para verificar diffs (default: claude)")

    # scope
    sc = sub.add_parser("scope", help="Descubre y delimita el perímetro de un subsistema tirando del hilo")
    sc.add_argument("--repo", default=".", help="Ruta al repo (default: .)")
    sc.add_argument("--seed", default="", help="Rutas semilla separadas por coma para tirar del hilo")
    sc.add_argument("--filter", default="", help="Subcadena para filtrar semillas o archivos")
    sc.add_argument("--max-depth", type=int, default=3, help="Profundidad máxima de importaciones (default: 3)")
    sc.add_argument("--no-tables", action="store_true", help="No incluir archivos vinculados por tablas compartidas")

    # run
    p = sub.add_parser("run", help="Pipeline completo: ticket → implementación → PR")
    p.add_argument("--repo", default=".", help="Ruta al repo (default: .)")
    p.add_argument("--ticket", required=True, help="Descripción del ticket")
    p.add_argument("--base", default="main", help="Rama base para el diff (default: main)")
    p.add_argument("--skip-pr", action="store_true", help="No crear PR al final")
    p.add_argument("--no-review", action="store_true", help="Saltar code review")
    p.add_argument("--model", default=None, help="Modelo o alias a usar (ej: flash, pro, claude)")

    return parser

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    check_system_prerequisites()

    # Resolver modelo para la sesión
    chosen_model = resolve_model(getattr(args, "model", None) or get_default_model())
    if getattr(args, "model", None):
        info(f"Modelo seleccionado: {chosen_model}")

    runner = AgyRunner(default_model=chosen_model)
    repo = str(Path(getattr(args, "repo", ".")).resolve())

    # Comandos que no requieren repositorio Git obligatorio
    if args.command == "test":
        success = run_self_test()
        sys.exit(0 if success else 1)

    if args.command == "doctor":
        run_doctor(repo, runner=runner)
        sys.exit(0)

    if args.command == "audit":
        deep_audit_loop(args.file, repo, max_rounds=args.rounds, runner=runner)
        sys.exit(0)

    if args.command == "triage":
        from pilot.engines.triage import triage_engine
        from pilot.engines.convergence import CumulativeMemory
        memory = CumulativeMemory.load_from_file(args.file)
        if memory.count() == 0:
            err("No se encontraron bugs para procesar.")
            sys.exit(1)
        
        target_bugs = memory.bugs
        if hasattr(args, "chunk_size") and args.chunk_size:
            start = args.chunk_start or 0
            target_bugs = target_bugs[start:start+args.chunk_size]
            info(f"Procesando bloque {start} a {start+len(target_bugs)-1} de {memory.count()} bugs totales.")
        
        info(f"Iniciando reclasificación de {len(target_bugs)} bugs con Kev 4B...")
        results = triage_engine.triage_batch(target_bugs, repo_path=args.repo)
        
        out_suffix = f"_chunk_{args.chunk_start}.json" if (hasattr(args, "chunk_size") and args.chunk_size) else "_TRIAGED.json"
        output_file = Path(args.file).with_suffix('.json').with_name(f"{Path(args.file).stem}{out_suffix}")
        output_file.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        ok(f"Triage completado exitosamente para {len(results)} bugs.")
        ok(f"Resultados guardados en: {output_file}")
        sys.exit(0)

    if args.command == "scope":
        from pilot.core.scope import ScopeDiscoveryEngine
        engine = ScopeDiscoveryEngine(repo)
        seeds = [s.strip() for s in args.seed.split(",") if s.strip()] if getattr(args, "seed", None) else None
        contract = engine.discover_contract(
            seed_files=seeds,
            filter_keyword=args.filter,
            max_depth=args.max_depth,
            include_shared_tables=not args.no_tables,
        )
        banner("CONTRATO DE ALCANCE DESCUBIERTO (SCOPE CONTRACT)")
        info(contract.summary)
        print()
        print(f"{Colors.BOLD}Archivos en el perímetro ({len(contract.target_files)}):{Colors.RESET}")
        for idx, f in enumerate(contract.relative_files, 1):
            print(f"  {idx:2d}. {Colors.CYAN}{f}{Colors.RESET}")
        if contract.shared_tables:
            print(f"\n{Colors.BOLD}Tablas de Base de Datos Vinculadas:{Colors.RESET}")
            for t in sorted(contract.shared_tables):
                print(f"  • {Colors.YELLOW}{t}{Colors.RESET}")
        if contract.external_perimeters:
            print(f"\n{Colors.BOLD}Fronteras / Servicios Externos:{Colors.RESET}")
            for ep in sorted(contract.external_perimeters):
                print(f"  ⚡ {Colors.MAGENTA}{ep}{Colors.RESET}")
        print()
        sys.exit(0)

    if args.command == "converge":
        seeds = [s.strip() for s in args.seed.split(",") if s.strip()] if getattr(args, "seed", None) else None
        res = run_convergence_loop(
            repo=repo,
            filter_keyword=args.filter,
            seed_files=seeds,
            memory_file=args.memory_file,
            scanner_model=args.scanner,
            verifier_model=args.verifier,
            max_lines_per_quadrant=args.quadrant_lines,
            max_cycles=args.cycles,
            clean_streak_target=args.clean_streak,
            output_report=args.output_report,
            max_depth=args.max_depth,
            include_shared_tables=not args.no_tables,
            runner=runner,
        )
        sys.exit(0 if res.get("convergencia_alcanzada") else 2)

    if args.command == "surgery":
        engine = SurgeryEngine(repo_path=repo, runner=runner)
        success = engine.run_surgery_batch(
            memory_file=args.file,
            surgeon_model=args.surgeon,
            auditor_model=args.auditor
        )
        sys.exit(0 if success else 1)


    if args.command == "sweep":
        scanner_m = resolve_model(args.scanner)
        verifier_m = resolve_model(args.verifier)
        exts = [e.strip() for e in args.ext.split(",") if e.strip()]
        continuous_sweep(
            repo=repo,
            scanner_model=scanner_m,
            verifier_model=verifier_m,
            extensions=exts,
            max_cycles=args.cycles,
            clean_cycles_to_stop=args.clean_streak,
            filter_keyword=args.filter,
            runner=runner,
        )

        sys.exit(0)


    # Comandos que requieren repositorio Git válido
    git_client = GitClient(repo)
    if not git_client.is_valid_repo():
        err(f"'{repo}' no es un repositorio git válido.")
        sys.exit(1)

    if args.command == "review":
        audit_branch(repo, base_branch=args.base, ticket=args.ticket, runner=runner)
    elif args.command == "run":
        execute_pipeline(
            ticket=args.ticket,
            repo=repo,
            base=args.base,
            skip_pr=args.skip_pr,
            no_review=args.no_review,
            runner=runner,
        )
