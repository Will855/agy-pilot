"""
Motor de Descubrimiento de Alcance y Trazado de Fronteras (Scope Discovery Engine).
Responsabilidad única: Identificar el perímetro completo de auditoría "tirando del hilo"
desde puntos de entrada (semillas) a través de dependencias directas, llamadores (callers),
tablas de base de datos compartidas y puntos finales de integración externa.

Resuelve el problema de los cuellos de botella y puntos ciegos entre módulos:
- No se limita a filtrar por nombre de carpeta o archivo.
- Rastrea el flujo transaccional completo: UI (Caller) → API Handler → Domain Service → DB Tables & RPCs → Webhook Reconciliation.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from pilot.core.ui import Colors, banner, info, ok, warn


@dataclass
class ScopeContract:
    seeds: list[str]
    target_files: list[Path] = field(default_factory=list)
    relative_files: list[str] = field(default_factory=list)
    shared_tables: set[str] = field(default_factory=set)
    external_perimeters: set[str] = field(default_factory=set)
    call_edges: list[tuple[str, str]] = field(default_factory=list)
    summary: str = ""


class ScopeDiscoveryEngine:
    """Rastreador estático de grafo de dependencias y estado compartido."""

    SUPPORTED_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".py", ".mts", ".mjs"}
    SKIP_DIRS = {"node_modules", ".git", ".next", "dist", "build", "coverage", "__pycache__", ".vscode"}

    def __init__(self, repo_path: Path | str):
        self.repo = Path(repo_path).resolve()

    def resolve_import_path(self, import_str: str, from_file: Path) -> Path | None:
        """Resuelve rutas relativas y alias de TypeScript (@/ -> src/)."""
        candidate_bases = []

        if import_str.startswith("@/"):
            # Alias de TypeScript común (@/ -> src/ o raíz)
            sub_path = import_str[2:]
            candidate_bases.append(self.repo / "src" / sub_path)
            candidate_bases.append(self.repo / sub_path)
        elif import_str.startswith("."):
            # Import relativo (JS/TS o Python)
            if from_file.suffix == ".py":
                m = re.match(r"^(\.+)(.*)$", import_str)
                if m:
                    dots, rest = m.groups()
                    level = len(dots)
                    base_dir = from_file.parent
                    for _ in range(level - 1):
                        base_dir = base_dir.parent
                    if rest:
                        sub_path = rest.replace(".", "/")
                        candidate_bases.append((base_dir / sub_path).resolve())
                    else:
                        candidate_bases.append(base_dir.resolve())
            else:
                candidate_bases.append((from_file.parent / import_str).resolve())
        else:
            # Import absoluto, podría ser Python
            if from_file.suffix == ".py":
                sub_path = import_str.replace(".", "/")
                candidate_bases.append((self.repo / sub_path).resolve())
                candidate_bases.append((self.repo / "src" / sub_path).resolve())
            else:
                return None

        for base in candidate_bases:
            # 1. Coincidencia exacta de archivo
            if base.is_file():
                return base
            # 2. Con extensiones estándar (probando tanto sufijo adicional como reemplazo)
            for ext in self.SUPPORTED_EXTENSIONS:
                appended = base.with_name(base.name + ext)
                if appended.is_file():
                    return appended
                with_ext = base.with_suffix(ext)
                if with_ext.is_file():
                    return with_ext
            # 3. Directorio con index file o __init__.py
            if base.is_dir():
                for ext in self.SUPPORTED_EXTENSIONS:
                    index_name = "__init__" if ext == ".py" else "index"
                    index_file = base / f"{index_name}{ext}"
                    if index_file.is_file():
                        return index_file

        return None


    def extract_imports(self, file_path: Path) -> list[Path]:
        """Extrae todos los archivos locales importados desde el archivo objetivo."""
        if not file_path.is_file():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        # Regex para TypeScript/JavaScript (import/from/require) y Python (import/from)
        patterns = [
            r'(?:import|from)\s+[\'"]([^\'"]+)[\'"]',
            r'require\([\'"]([^\'"]+)[\'"]\)',
            r'from\s+([a-zA-Z0-9_\.]+)\s+import',
        ]

        found_paths = []
        for p in patterns:
            for match in re.findall(p, content):
                resolved = self.resolve_import_path(match, file_path)
                if resolved and resolved.exists() and resolved != file_path:
                    found_paths.append(resolved)

        return found_paths

    def extract_database_entities(self, file_path: Path) -> tuple[set[str], set[str]]:
        """Extrae nombres de tablas SQL (.from('table')) y RPCs (.rpc('proc'))."""
        if not file_path.is_file():
            return set(), set()

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return set(), set()

        tables = set(re.findall(r"\.from\(['\"]([a-zA-Z0-9_]+)['\"]\)", content))
        tables.update(re.findall(r"(?:FROM|JOIN|INTO|UPDATE)\s+public\.([a-zA-Z0-9_]+)", content, re.IGNORECASE))
        rpcs = set(re.findall(r"\.rpc\(['\"]([a-zA-Z0-9_]+)['\"]\)", content))

        return tables, rpcs

    def extract_external_perimeters(self, file_path: Path) -> set[str]:
        """Detecta fronteras con pasarelas o servicios externos."""
        if not file_path.is_file():
            return set()

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return set()

        perimeters = set()
        if "stripe" in content.lower():
            perimeters.add("Stripe API / SDK")
        if "redis" in content.lower() or "checkratelimit" in content.lower():
            perimeters.add("Redis Rate Limiter")
        if "livekit" in content.lower() or "accesstoken" in content.lower():
            perimeters.add("LiveKit Video Gateway")
        if "resend" in content.lower() or "nodemailer" in content.lower():
            perimeters.add("Email Gateway")
        if "supabase" in content.lower() or "createadminclient" in content.lower():
            perimeters.add("Supabase PostgREST / Admin RLS")

        return perimeters

    def find_inbound_callers(self, target_files: set[Path]) -> set[Path]:
        """
        Encuentra archivos que llaman a los objetivos hacia atrás:
        - Componentes UI que invocan la ruta o el servicio (fetch('/api/...'))
        - Modales, Server Actions o páginas consumidoras.
        """
        callers = set()
        routes_to_match = set()

        for tf in target_files:
            rel = str(tf.relative_to(self.repo))
            # Si es una ruta Next.js (ej: src/app/api/checkout/route.ts -> /api/checkout)
            if "app/api/" in rel:
                m = re.search(r"app(/api/[^/]+(?:/[^/]+)*)/route\.[a-z]+", rel)
                if m:
                    routes_to_match.add(m.group(1))

        for f in self.repo.rglob("*"):
            if not f.is_file() or f.suffix not in self.SUPPORTED_EXTENSIONS:
                continue
            if any(part in self.SKIP_DIRS for part in f.parts):
                continue
            if f in target_files:
                continue

            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Check 1: Llama explícitamente a las rutas API descubiertas
            for r in routes_to_match:
                if r in content:
                    callers.add(f)
                    break

            # Check 2: Importa directamente alguno de los target files
            for tf in target_files:
                rel_no_ext = str(tf.relative_to(self.repo)).replace("\\", "/").rsplit(".", 1)[0]
                mod_name = tf.stem
                if mod_name in content:
                    alias_paths = [f"@/{rel_no_ext}"]
                    if rel_no_ext.startswith("src/"):
                        alias_paths.append(f"@/{rel_no_ext[4:]}")
                        
                    is_caller = False
                    if any(alias in content for alias in alias_paths):
                        is_caller = True
                    elif f"./{mod_name}" in content and f.parent == tf.parent:
                        is_caller = True
                        
                    if is_caller:
                        callers.add(f)
                        break

        return callers

    def find_files_sharing_tables(self, tables: set[str], existing_targets: set[Path]) -> set[Path]:
        """
        Encuentra archivos que operan sobre las MISMAS tablas de base de datos
        (ej: checkout.service y webhooks/payments ambos tocan 'orders').
        """
        if not tables:
            return set()

        coupled_files = set()
        for f in self.repo.rglob("*"):
            if not f.is_file() or f.suffix not in self.SUPPORTED_EXTENSIONS:
                continue
            if any(part in self.SKIP_DIRS for part in f.parts):
                continue
            if f in existing_targets:
                continue

            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            extracted_tables_sql = set(re.findall(r"(?:FROM|JOIN|INTO|UPDATE)\s+public\.([a-zA-Z0-9_]+)", content, re.IGNORECASE))

            for t in tables:
                pattern = f".from('{t}')"
                pattern_dq = f'.from("{t}")'
                if pattern in content or pattern_dq in content or t in extracted_tables_sql:
                    coupled_files.add(f)
                    break

        return coupled_files

    def discover_contract(
        self,
        seed_files: list[str | Path] | None = None,
        filter_keyword: str | None = None,
        max_depth: int = 3,
        include_shared_tables: bool = True,
    ) -> ScopeContract:
        """Descubre el contrato de alcance a partir de semillas o palabras clave de filtrado."""
        keywords = [k.strip().lower() for k in filter_keyword.split(",") if k.strip()] if filter_keyword else []

        seeds: list[Path] = []
        if seed_files:
            for s in seed_files:
                sp = (self.repo / s).resolve() if not Path(s).is_absolute() else Path(s).resolve()
                if sp.exists():
                    try:
                        sp.relative_to(self.repo)
                        seeds.append(sp)
                    except ValueError:
                        pass
        elif keywords:
            for ext in self.SUPPORTED_EXTENSIONS:
                for f in self.repo.rglob(f"*{ext}"):
                    if not any(part in self.SKIP_DIRS for part in f.parts) and f.is_file():
                        rel_str = str(f.relative_to(self.repo)).lower()
                        if any(kw in rel_str for kw in keywords):
                            seeds.append(f)

        if not seeds and not seed_files and not filter_keyword:
            target_files = []
            for ext in self.SUPPORTED_EXTENSIONS:
                for f in self.repo.rglob(f"*{ext}"):
                    if not any(part in self.SKIP_DIRS for part in f.parts) and f.is_file():
                        target_files.append(f)
            sorted_files = sorted(target_files, key=lambda x: str(x.relative_to(self.repo)))
            return ScopeContract(
                seeds=[],
                target_files=sorted_files,
                relative_files=[str(f.relative_to(self.repo)) for f in sorted_files],
                summary=f"Alcance descubierto (repositorio completo): {len(sorted_files)} archivos.",
            )

        return self.discover_scope(seeds, max_depth=max_depth, include_shared_tables=include_shared_tables)

    def discover_scope(
        self,
        seeds: list[Path | str],
        max_depth: int = 3,
        include_shared_tables: bool = True,
    ) -> ScopeContract:
        """
        Tira del hilo de forma integral:
        1. Semillas iniciales.
        2. Trazado hacia adelante (Imports y Callees) hasta max_depth.
        3. Trazado hacia atrás (Inbound Callers en UI y Actions).
        4. Acoplamiento de datos (archivos que reconcilian las mismas tablas SQL).
        5. Identificación de fronteras externas (Stripe, Redis, etc.).
        """
        resolved_seeds: list[Path] = []
        for s in seeds:
            p = (self.repo / s).resolve() if not Path(s).is_absolute() else Path(s).resolve()
            try:
                p.relative_to(self.repo)
            except ValueError:
                continue
                
            if p.is_file():
                resolved_seeds.append(p)
            elif p.is_dir():
                for ext in self.SUPPORTED_EXTENSIONS:
                    resolved_seeds.extend([f for f in p.rglob(f"*{ext}") if not any(part in self.SKIP_DIRS for part in f.parts)])

        all_discovered: set[Path] = set(resolved_seeds)
        call_edges: list[tuple[str, str]] = []
        all_tables: set[str] = set()
        all_perimeters: set[str] = set()

        # ── 1. Trazado Hacia Adelante (Forward / Callees) ────────────────────────
        current_layer = set(resolved_seeds)
        for depth in range(1, max_depth + 1):
            next_layer = set()
            for src_file in current_layer:
                deps = self.extract_imports(src_file)
                for dep in deps:
                    edge = (str(src_file.relative_to(self.repo)), str(dep.relative_to(self.repo)))
                    if edge not in call_edges:
                        call_edges.append(edge)
                    if dep not in all_discovered:
                        all_discovered.add(dep)
                        next_layer.add(dep)

                # Extraer entidades de datos y fronteras
                t, _ = self.extract_database_entities(src_file)
                all_tables.update(t)
                all_perimeters.update(self.extract_external_perimeters(src_file))

            current_layer = next_layer
            if not current_layer:
                break

        # ── 2. Trazado Hacia Atrás (Inbound / Callers) ──────────────────────────
        inbound_callers = self.find_inbound_callers(all_discovered)
        for caller in inbound_callers:
            all_discovered.add(caller)
            t, _ = self.extract_database_entities(caller)
            all_tables.update(t)
            all_perimeters.update(self.extract_external_perimeters(caller))

        # ── 3. Acoplamiento por Tablas Compartidas (Shared State) ────────────────
        if include_shared_tables and all_tables:
            # Filtrar tablas altamente genéricas para evitar falsos positivos masivos
            specific_tables = {t for t in all_tables if t not in {"profiles", "users", "migrations"}}
            coupled = self.find_files_sharing_tables(specific_tables, all_discovered)
            for cf in coupled:
                # Solo incluir si está en rutas clave de servicios o api
                rel = str(cf.relative_to(self.repo))
                if any(k in rel.lower() for k in ["api", "service", "action", "webhook"]):
                    all_discovered.add(cf)
                    all_perimeters.update(self.extract_external_perimeters(cf))

        # Ordenar lista final de archivos por importancia y ruta
        sorted_files = sorted(list(all_discovered), key=lambda x: str(x.relative_to(self.repo)))
        rel_files = [str(f.relative_to(self.repo)) for f in sorted_files]

        summary = (
            f"Alcance descubierto: {len(sorted_files)} archivos interconectados. "
            f"Tablas compartidas: {', '.join(sorted(all_tables)) or 'Ninguna'}. "
            f"Fronteras externas: {', '.join(sorted(all_perimeters)) or 'Ninguna'}."
        )

        return ScopeContract(
            seeds=[str(s.relative_to(self.repo)) for s in resolved_seeds],
            target_files=sorted_files,
            relative_files=rel_files,
            shared_tables=all_tables,
            external_perimeters=all_perimeters,
            call_edges=call_edges,
            summary=summary,
        )
