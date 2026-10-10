import httpx, json, sys

QUESTIONS_SCHEMA = {
    "is_hallucination": {"type": "noul"},
    "impact_score": {"type": "score", "options": ["None", "Low", "Medium", "High", "Critical"]}
}

state = """File: src/app/api/owner/plans/route.ts
Observed Issue: Bypass Total P0: Upgrade Gratuito a Planes de Pago
Code Snippet:
    if (!paymentIntentId && !isTesterBypass) {
      const result = await confirmPlanPayment(profile.id, planId, billingPeriod)
      if (!result.success) { ... }
    }
    const result = await confirmPlanPayment(profile.id, planId, billingPeriod, paymentIntentId, isTesterBypass)
"""

prompt = f"System: Eres Kev 4B.\nUser: Evalúa este bug.\n{state}\nOutput format: {json.dumps(QUESTIONS_SCHEMA)}"
r = httpx.post("http://127.0.0.1:8008/v1/chat/completions", json={"model": "kev-latest", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}, timeout=120.0)
print(r.json())
