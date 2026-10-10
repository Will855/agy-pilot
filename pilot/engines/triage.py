"""
Motor de Triaje en Lote: Transforma bugs empíricos en asignaciones tipadas.
"""
from typing import Any
from pilot.core.decision_client import decision_client
from pilot.core.ui import info, ok, warn

QUESTIONS_SCHEMA = {
    "is_hallucination": {
        "type": "noul",
        "instructions": "Does this report assume non-existent variables, impossible control flows, or fabricated APIs?"
    },
    "impact_score": {
        "type": "score",
        "instructions": "Evaluate the architectural blast radius if exploited in production.",
        "criteria": [
            "Trivial / Cosmetic",
            "Minor edge-case",
            "Functional degradation",
            "High business impact / data leak",
            "Catastrophic / complete system takeover"
        ]
    },
    "domain_role": {
        "type": "choice",
        "instructions": "Which specialized engineering archetype is required to remediate this flaw?",
        "criteria": {
            "FINTECH_SECURITY": "Payment gateways, Stripe webhooks, billing subscriptions, idempotency",
            "DATABASE_RLS": "PostgreSQL, Supabase RLS policies, migrations, lock deadlocks, data isolation",
            "CONCURRENCY_SYNC": "Race conditions, booking calendar overlaps, outbox event delivery, queues",
            "AUTH_SESSION": "JWT validation, role-based access control, privilege escalation, token expiry",
            "UI_STATE_INTEGRITY": "React re-render loops, stale closures, client-side data desynchronization"
        }
    },
    "defense_skill": {
        "type": "choice",
        "instructions": "Select the primary defensive skill required to verify and patch this bug.",
        "criteria": {
            "stripe-webhook-guard": "Webhook signature verification and replay attack prevention",
            "supabase-rls-auditor": "Multi-tenant Row Level Security isolation contracts",
            "calendar-race-detector": "Distributed locking and atomic slot reservation",
            "jwt-session-validator": "Cryptographic token verification and claims enforcement",
            "react-closure-guard": "Safe asynchronous state handling and hook dependencies"
        }
    }
}

class TriageEngine:
    def __init__(self):
        self.client = decision_client

    def triage_batch(self, raw_bugs: list[dict[str, Any]], repo_path: str = None) -> list[dict[str, Any]]:
        info(f"  [TRIAGE] Sometiendo lote de {len(raw_bugs)} bug(s) al arbitraje de Kev 4B...")
        processed = []

        for i, bug in enumerate(raw_bugs, 1):
            if not bug.get("id"):
                bug["id"] = f"SEC-{i}"

            file_content = "Contexto no disponible."
            if repo_path and bug.get("archivo"):
                try:
                    import os
                    from pathlib import Path
                    p = Path(repo_path) / bug["archivo"]
                    if p.exists():
                        raw_content = p.read_text(encoding="utf-8")[:20000]
                        # Usar Gemini Flash para extraer el fragmento exacto
                        from pilot.core.runner import default_runner
                        from pilot.config import resolve_model
                        prompt = f"""
Extrae TODO el bloque o bloques de código de este archivo que estén relacionados con el siguiente bug. 
No te limites a un número de líneas. Si el bug requiere el contexto de 100 o 200 líneas (ej. una clase entera o el flujo completo de una función), extrae todo lo necesario para que un auditor pueda validar la vulnerabilidad sin quedarse a ciegas.

Bug: {bug.get('descripcion')}

Archivo:
{raw_content}

Solo devuelve el código crudo, sin formato markdown ni explicaciones adicionales.
"""
                        _, extracted = default_runner.run(prompt, repo_path, new_project=True, model=resolve_model("flash"))
                        file_content = extracted.strip()
                        if not file_content:
                            file_content = raw_content[:1000]
                except Exception:
                    pass

            state = (
                f"File: {bug.get('archivo')}\n"
                f"Line: {bug.get('linea_aprox', 'Unknown')}\n"
                f"Observed Issue: {bug.get('descripcion')}\n"
                f"Reproduction Test Case: {bug.get('caso_de_prueba')}\n"
                f"Code Snippet:\n{file_content}"
            )

            answers = self.client.evaluate(state, QUESTIONS_SCHEMA)

            # 1. Filtro Anti-Alucinación
            hallucination_prob = (answers.get("is_hallucination") or {}).get("noul", 0.0)
            if hallucination_prob > 0.65:
                warn(f"  ⚠ [{bug['id']}] Descartado como alucinación teórica (confianza: {hallucination_prob:.2f})")
                continue

            # 2. Severidad Calibrada
            raw_score = (answers.get("impact_score") or {}).get("score", 2.5)
            if raw_score >= 3.8:
                canonical_sev = "CRITICA"
            elif raw_score >= 3.0:
                canonical_sev = "ALTA"
            elif raw_score >= 1.8:
                canonical_sev = "MEDIA"
            else:
                canonical_sev = "BAJA"

            # 3. Dominio y Skill
            domain = (answers.get("domain_role") or {}).get("choice", "FINTECH_SECURITY")
            skill = (answers.get("defense_skill") or {}).get("choice", "stripe-webhook-guard")

            triaged_bug = dict(bug)
            triaged_bug["severidad"] = canonical_sev
            triaged_bug["score_calibrado"] = round(raw_score, 2)
            triaged_bug["dominio_asignado"] = domain
            triaged_bug["skill_recomendada"] = skill
            processed.append(triaged_bug)
            ok(f"  ✓ [{triaged_bug['id']}][{canonical_sev}] {domain} -> {skill}")

        return processed

triage_engine = TriageEngine()
