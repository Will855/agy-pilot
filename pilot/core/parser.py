"""
Extractor y saneador robusto de respuestas JSON generadas por LLMs.
Responsabilidad única: Parseo resiliente de JSON evitando fallos por caracteres especiales o backticks.
"""

import json
import re

from pilot.config import LOGS_DIR
from pilot.core.ui import warn

def extract_json(text: str, context: str = "") -> dict | list:
    """
    Extrae un objeto o lista JSON desde una respuesta de modelo.
    Aplica cascada de 6 niveles de recuperación sin corromper URLs ni caracteres de escape.
    Detecta señales canónicas de parada y convergencia (REPO_LIMPIO, CONVERGENCIA TOTAL ALCANZADA).
    """
    if not text or not text.strip():
        raise ValueError("Texto vacío recibido para extracción de JSON.")

    # Detección inmediata de señales canónicas de parada y convergencia
    clean_markers = [
        "[CONVERGENCIA TOTAL ALCANZADA",
        "CONVERGENCIA TOTAL ALCANZADA: 0 NUEVOS BUGS",
        "CONVERGENCIA TOTAL ALCANZADA",
        "REPO_LIMPIO",
        "QUADRANT_LIMPIO",
        "LENTE_LIMPIA",
    ]
    if any(marker in text for marker in clean_markers):
        return {
            "convergencia_alcanzada": True,
            "veredicto": "APROBADO",
            "hallazgos": [],
            "resumen": "Convergencia total alcanzada: 0 nuevos bugs detectados.",
        }

    # Nivel 1: Bloques etiquetados ```json ... ``` o ``` ... ```
    match = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if match:
        raw = match.group(1)
    else:
        match = re.search(r"```\s*([\s\S]+?)\s*```", text)
        raw = match.group(1) if match else text

    # Nivel 1A: Parseo directo sin alterar contenido crudo (protege URLs con // y rutas)
    for target in [raw.strip(), text.strip()]:
        for strict_val in [False, True]:
            try:
                return json.loads(target, strict=strict_val)
            except Exception:
                pass

    # Nivel 2: Buscar el contenedor {...} o [...] más externo (tanto greedy como non-greedy)
    for pattern in [r"(\{[\s\S]*\}|\[[\s\S]*\])", r"(\{[\s\S]+?\}(?=\s*$|\s*```|\n\n))"]:
        m2 = re.search(pattern, raw)
        if m2:
            for strict_val in [False, True]:
                try:
                    return json.loads(m2.group(1), strict=strict_val)
                except Exception:
                    pass

    # Nivel 3: Limpiar trailing commas (ej: {"a": 1, })
    try:
        no_trailing = re.sub(r",\s*([\}\]])", r"\1", raw)
        return json.loads(no_trailing, strict=False)
    except Exception:
        pass

    # Nivel 4: Normalización de backslashes escapados incorrectamente
    try:
        sanitized = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', raw)
        return json.loads(sanitized, strict=False)
    except Exception:
        pass

    # Nivel 5: Fallback seguro a ast.literal_eval (si el modelo devolvió sintaxis de dict de Python: True/False/None)
    try:
        import ast
        py_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if py_match:
            candidate = ast.literal_eval(py_match.group(1).strip())
            if isinstance(candidate, (dict, list)):
                return candidate
    except Exception:
        pass

    # Nivel 6: Extracción heurística resiliente si el modelo respondió en formato de reporte Markdown
    verdict_m = re.search(r"Veredicto[:\s*`]+(APROBADO_CON_OBSERVACIONES|APROBADO|RECHAZADO)", text, re.IGNORECASE)
    if verdict_m:
        verdict = verdict_m.group(1).upper()
        findings = []
        md_pattern = r"###\s*(?:[^\n]*?)Hallazgo\s*\d*\s*—?\s*(?:\[?(CRITICA|ALTA|MEDIA|BAJA)\]?)?\s*\|\s*([^\n]+)([\s\S]*?)(?=###|$)"
        for h_m in re.finditer(md_pattern, text, re.IGNORECASE):
            sev = (h_m.group(1) or "MEDIA").upper()
            header = h_m.group(2).strip()
            body = h_m.group(3).strip()

            title_m = re.search(r"\*\*([^*]+)\*\*", body)
            title = title_m.group(1).strip() if title_m else ""
            full_desc = f"{title} ({header})" if title else header

            findings.append({
                "severidad": sev,
                "descripcion": full_desc,
                "archivo": header.split(",")[0].strip().replace("`", ""),
                "detalle": body[:500],
            })
        return {
            "veredicto": verdict,
            "hallazgos": findings,
            "resumen": "Reporte estructurado extraído de análisis Markdown del auditor.",
        }

    # Si todo falla, emitir alerta de diagnóstico con preview
    preview = text[:600].replace("\n", "\\n")
    warn(f"No se pudo parsear JSON ({context}). Output recibido:\n  {preview}")
    from pilot.config import get_logs_dir
    raise ValueError(f"JSON inválido — revisa el log en {get_logs_dir()}/")


