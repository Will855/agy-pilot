"""
Motor de Auto-Prueba y Verificación del Orquestador (self-test).
Aplica la filosofía de 'la terminal tiene el voto final' contra el propio agy-pilot.
Verifica que todos los subsistemas, parsers, contratos de verificación y fallbacks funcionen con exit code 0.
"""

from pathlib import Path
import tempfile

from pilot.config import MODEL_ALIASES, get_logs_dir, resolve_model
from pilot.core.parser import extract_json
from pilot.core.runner import AgentRunner
from pilot.core.shell import run_command_args
from pilot.core.ui import Colors, banner, err, info, ok
from pilot.engines.convergence import (
    CumulativeMemory,
    Quadrant,
    partition_into_quadrants,
)

class MockAgentRunner:
    """Runner de prueba determinista para validar los motores sin gastar tokens ni invocar agy."""
    def __init__(self, canned_response: str = "PILOTOK", exit_code: int = 0):
        self.canned_response = canned_response
        self.exit_code = exit_code
        self.calls: list[dict] = []

    def run(self, prompt: str, repo_path: str, new_project: bool = True, model: str | None = None) -> tuple[int, str]:
        self.calls.append({
            "prompt": prompt,
            "repo_path": repo_path,
            "new_project": new_project,
            "model": model,
        })
        return self.exit_code, self.canned_response

def run_self_test() -> bool:
    banner("AUTO-AUDITORÍA Y STRESS TEST DE AGY-PILOT", Colors.CYAN)
    tests_passed = 0
    tests_total = 0

    def assert_test(name: str, condition: bool, detail: str = "") -> None:
        nonlocal tests_passed, tests_total
        tests_total += 1
        if condition:
            ok(f"[PASS] {name}")
            tests_passed += 1
        else:
            err(f"[FAIL] {name} - {detail}")

    # ── 1. TEST DE CONFIGURACIÓN Y MODELOS ───────────────────────────────────────
    info("Probando resolución de catálogo de modelos...")
    assert_test("Alias 'flash' resuelve a gemini-3.8-flash-high", resolve_model("flash") == "gemini-3.8-flash-high")
    assert_test("Alias 'claude' resuelve a claude-sonnet-4-6", resolve_model("claude") == "claude-sonnet-4-6")
    assert_test("Alias 'pro' resuelve a gemini-3.1-pro-high", resolve_model("pro") == "gemini-3.1-pro-high")
    assert_test("Modelo desconocido se preserva intacto", resolve_model("custom-model-x") == "custom-model-x")

    # ── 2. TEST DE PERSISTENCIA Y DIRECTORIO DE LOGS ──────────────────────────────
    info("Probando resiliencia de almacenamiento...")
    logs_dir = get_logs_dir()
    assert_test("Directorio de logs existe y es accesible", logs_dir.exists())

    # ── 3. TEST DE EXTRACTOR DE JSON RESILIENTE (Adversarial) ────────────────────
    info("Probando extractor de JSON bajo ataques y formatos irregulares...")

    # Caso 3.1: JSON estándar con backticks
    j1 = extract_json("```json\n{\"ok\": true, \"count\": 10}\n```")
    assert_test("Parseo estándar con triple backticks", isinstance(j1, dict) and j1.get("ok") is True and j1.get("count") == 10)

    # Caso 3.2: URL intacta (sin romper //)
    j2 = extract_json('{"url": "https://api.stripe.com/v1/charges", "file": "file:///path/to/code"}')
    assert_test("Preserva URLs con '//' intactas", isinstance(j2, dict) and j2.get("url") == "https://api.stripe.com/v1/charges")

    # Caso 3.3: Trailing commas que rompen json.loads estándar
    j3 = extract_json('```json\n{"item1": "val1", "item2": "val2", }\n```')
    assert_test("Tolerancia a trailing commas", isinstance(j3, dict) and j3.get("item1") == "val1")

    # Caso 3.4: Sintaxis Python dictionary con True/False/None
    j4 = extract_json("Resultado:\n{'activo': True, 'borrado': False, 'vencimiento': None}")
    assert_test("Tolerancia a sintaxis de dict de Python (True/False/None)", isinstance(j4, dict) and j4.get("activo") is True and j4.get("vencimiento") is None)

    # Caso 3.5: Texto mixto antes y después del bloque JSON
    j5 = extract_json("Explicación previa del modelo...\n```\n[{\"id\": 1}, {\"id\": 2}]\n```\nNotas adicionales...")
    assert_test("Extracción de lista JSON rodeada de texto arbitrario", isinstance(j5, list) and len(j5) == 2 and j5[0]["id"] == 1)

    # Caso 3.6: Reporte Markdown con emojis y títulos (estilo Claude Sonnet)
    md_review = """
## Veredicto: `APROBADO_CON_OBSERVACIONES`
---
### 🔴 Hallazgo 1 — ALTA | src/app/api/webhooks/route.ts, línea ~219
**Lógica de detección de reembolso total/parcial con condición invertida**
Prueba concreta: Evento charge.refunded...
### 🟡 Hallazgo 2 — MEDIA | src/services/checkout.ts, línea 94
**Bypass de producción**
"""
    j6 = extract_json(md_review)
    assert_test("Extracción de reporte Markdown con emojis y títulos",
                isinstance(j6, dict) and j6.get("veredicto") == "APROBADO_CON_OBSERVACIONES" and len(j6.get("hallazgos", [])) == 2)

    # Caso 3.7: Detección canónica de convergencia
    j7 = extract_json("Análisis completado sin hallazgos. [CONVERGENCIA TOTAL ALCANZADA: 0 NUEVOS BUGS]")
    assert_test("Detección de señal canónica de convergencia",
                isinstance(j7, dict) and j7.get("convergencia_alcanzada") is True and j7.get("veredicto") == "APROBADO")

    # ── 4. TEST DE SEGURIDAD EN EJECUCIÓN DE COMANDOS (Shell Safety) ────────────
    info("Probando ejecución segura de comandos sin shell=True...")
    code, stdout, _ = run_command_args(["echo", "hello \"world\" with $SPECIAL and 'quotes'"])
    assert_test("run_command_args preserva comillas y caracteres sin inyección",
                code == 0 and "hello \"world\" with $SPECIAL and 'quotes'" in stdout.strip())

    # ── 5. TEST DE MEMORIA ACUMULATIVA (Cumulative Memory) ───────────────────────
    info("Probando motor de memoria acumulativa...")
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as tf:
        tf.write("""# Informe
| ID | Dominio | Tipo | Severidad | Archivo | Barrido |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | Planes | Price Tampering | CRITICA | `src/services/plans.ts` | 1 |
| **SEC-02** | Tienda | Replay Attack | ALTA | `src/app/checkout.ts` | 1 |
""")
        temp_report = tf.name

    mem = CumulativeMemory.load_from_file(temp_report)
    Path(temp_report).unlink(missing_ok=True)
    assert_test("Carga de tabla Markdown en memoria acumulativa", mem.count() == 2)
    assert_test("Deduplicación evita registrar el mismo bug dos veces",
                mem.add_bug({"id": "SEC-01", "archivo": "src/services/plans.ts", "descripcion": "Price Tampering"}) is False)
    assert_test("Añadir nuevo bug incrementa el conteo y asigna ID correlativo",
                mem.add_bug({"archivo": "src/services/video.ts", "descripcion": "Token bypass"}) is True and mem.count() == 3)
    ctx = mem.to_prompt_context()
    assert_test("Contexto para prompt incluye cláusula de exclusión y IDs", "NO REPITAS NINGUNO" in ctx and "SEC-01" in ctx)

    # ── 6. TEST DE PARTICIONADO EN CUADRANTES ACOTADOS (Quadrant Chunking) ──────
    info("Probando particionado de alcance en cuadrantes acotados...")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        f1 = tdp / "small1.ts"
        f1.write_text("\n".join(f"const a{i} = {i}" for i in range(100)))
        f2 = tdp / "small2.ts"
        f2.write_text("\n".join(f"const b{i} = {i}" for i in range(150)))
        f3 = tdp / "large.ts"
        f3.write_text("\n".join(f"const c{i} = {i}" for i in range(500)))

        quads = partition_into_quadrants(tdp, [f1, f2, f3], max_lines_per_quadrant=300)
        assert_test("Particiona correctamente respetando límites de líneas", len(quads) >= 2)
        assert_test("Archivo grande se aísla en cuadrante individual", any(q.total_lines >= 500 for q in quads))

    # ── 7. TEST DE DESCUBRIMIENTO DE ALCANCE Y TRAZADO DE FRONTERAS (Scope Discovery) ──
    info("Probando motor de descubrimiento de alcance y trazado de dependencias...")
    from pilot.core.scope import ScopeDiscoveryEngine
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        src_dir = tdp / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        api_dir = src_dir / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        svc_dir = src_dir / "services"
        svc_dir.mkdir(parents=True, exist_ok=True)

        service_file = svc_dir / "payment.service.ts"
        service_file.write_text("""
        import { admin } from '@/lib/db';
        export async function charge() {
            return admin.from('orders').select('*');
        }
        """)

        route_file = api_dir / "route.ts"
        route_file.write_text("""
        import { charge } from '@/services/payment.service';
        import stripe from 'stripe';
        export async function POST() { await charge(); }
        """)

        engine = ScopeDiscoveryEngine(tdp)
        contract = engine.discover_scope([route_file], max_depth=2)

        assert_test("Resuelve import con alias @/ y conecta archivos", len(contract.target_files) == 2)
        assert_test("Detecta entidades de base de datos compartidas (.from('orders'))", "orders" in contract.shared_tables)
        assert_test("Detecta fronteras externas (Stripe API)", any("Stripe" in p for p in contract.external_perimeters))

    # ── 8. TEST DE CONTRATO DEL RUNNER (Dependency Inversion) ─────────────────────
    info("Probando abstracción de ejecución con MockAgentRunner...")
    mock = MockAgentRunner(canned_response="{\"veredicto\": \"APROBADO\", \"hallazgos\": []}", exit_code=0)
    code, out = mock.run("Test prompt", "/fake/repo", model="claude-sonnet-4-6")
    assert_test("Mock runner cumple protocolo AgentRunner", code == 0 and "APROBADO" in out)
    assert_test("Mock runner registra parámetros de llamada", len(mock.calls) == 1 and mock.calls[0]["model"] == "claude-sonnet-4-6")

    # ── REPORTE FINAL ─────────────────────────────────────────────────────────────
    print()
    if tests_passed == tests_total:
        ok(f"Todos los tests pasaron: {tests_passed}/{tests_total} contratos verificados exitosamente. ✅")
        return True
    else:
        err(f"Fallaron {tests_total - tests_passed} de {tests_total} tests.")
        return False


