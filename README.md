# agy-pilot v3 — Orquestador de desarrollo IA

Sistema de automatización en terminal que transforma tickets en Pull Requests verificadas mediante una línea de montaje de micro-agentes especializados.

---

## ⚡ Instalación y acceso rápido

Ya está configurado como binario global en tu entorno:

```bash
agy-pilot --help
```

---

## 🩺 Diagnóstico previo (`doctor`)

Antes de lanzar un pipeline o si cambiaste de entorno, verifica que todo esté en verde:

```bash
agy-pilot doctor
```

Comprueba automáticamente:
* Disponibilidad y conectividad de `agy` CLI con un ping real.
* Configuración de Git y permisos de escritura en logs.
* Estado del CLI de GitHub (`gh`) para creación de Pull Requests.

---

## 🚀 Comandos principales

### 1. Diagnóstico del entorno
```bash
agy-pilot doctor
```

### 2. Revisión de cambios de tu rama (`review`)
Audita el `git diff` completo de la rama donde estás trabajando contra `main` (o contra otra rama base) aplicando las 4 lentes de seguridad:

```bash
# Estando en la carpeta de tu repositorio
agy-pilot review

# O indicando una rama base diferente
agy-pilot review --base develop
```

### 3. Pipeline completo: Ticket → PR (`run`)
Ejecuta la línea de montaje completa (auditoría previa, desglose en micro-tareas con pruebas obligatorias, bucle cerrado de implementación, revisión final de seguridad y apertura de Draft PR):

```bash
agy-pilot run --ticket "Implementar autenticación con JWT y refresh token"
```

Opciones útiles:
* `--skip-pr`: Implementa y hace commits locales sin abrir Pull Request remota.
* `--no-review`: Omite la fase de code review final.

### 4. Auditoría profunda de un archivo (`audit`)
Aplica el bucle de agotamiento con las técnicas de **Abogado del Diablo** y **Lentes Temáticos** sobre un archivo o módulo crítico hasta no encontrar más bugs comprobables:

```bash
agy-pilot audit --file src/services/auth.service.ts --rounds 4
```

### 5. Auditoría continua dual-modelo en todo el repositorio (`sweep`)
Escaneo perpetuo hasta agotar vulnerabilidades en todo el proyecto: **Flash High** analiza y aplica fixes; **Claude Sonnet** actúa como fiscal verificador (cero código generado por Claude). Para automáticamente tras 2 ciclos limpios consecutivos:

```bash
# Ejecutar sweep en tu proyecto
agy-pilot sweep --repo ~/mi-proyecto --ext ts,tsx,py

# Personalizar modelos y límite de ciclos
agy-pilot sweep --repo . --scanner flash --verifier claude --cycles 8 --clean-streak 2
```

### 6. Motor de Convergencia Multi-Barrido con Memoria Acumulativa (`converge`)
Diseñado para auditorías de alta intensidad sobre dominios complejos (ej: pasarelas de pago, auth, RBAC). Subdivide el alcance en **cuadrantes acotados** de ~350 líneas e inyecta la memoria acumulativa de bugs previos (ej: `SEC-01` a `SEC-21`) para no repetir hallazgos:

```bash
# Barrido con ingesta de memoria previa de bugs ya descubiertos:
agy-pilot converge \
  --repo ~/mi-proyecto \
  --filter "checkout,payment,stripe,plan" \
  --memory-file docs/reports/INFORME_auditoria_seguridad_ecosistema_pagos.md \
  --scanner flash \
  --verifier claude \
  --quadrant-lines 350 \
  --cycles 5 \
  --clean-streak 1
```

---

## ⚙️ Configuración y selección de modelos

Puedes elegir el modelo pasando el flag `--model` directamente en cualquier comando, o usando la variable de entorno `PILOT_MODEL`:

```bash
# Vía flag CLI con alias amigables:
agy-pilot doctor --model pro
agy-pilot review --model claude
agy-pilot run --ticket "..." --model flash

# O mediante variable de entorno:
PILOT_MODEL=pro agy-pilot run --ticket "..."
```

### Alias rápidos soportados:
* `flash` ➔ `gemini-3.8-flash-high` (Rápido, ideal para tareas atómicas y auditorías continuas - **Default**)
* `flash-med` ➔ `gemini-3.8-flash-medium`
* `pro` ➔ `gemini-3.1-pro-high` (Razonamiento profundo para tickets de arquitectura compleja)
* `claude` ➔ `claude-sonnet-4-6` (Meticuloso, ideal para revisiones de seguridad críticas)
* `opus` ➔ `claude-opus-4-6-thinking`

---

## 🏛️ Arquitectura Modular (Principios SOLID)

El sistema ha sido desacoplado en el paquete Python `pilot/` eliminando el código monolítico:

```
~/scripts/agy-pilot/
├── agy-pilot             # Wrapper ejecutable (resuelve symlinks a ~/bin/)
├── agy_pilot.py          # Fachada retrocompatible y punto de entrada
├── pilot/                # Paquete modular desacoplado
│   ├── cli.py            # Responsabilidad Única: Parseo y despacho de argumentos
│   ├── config.py         # Constantes, catálogo de modelos y rutas
│   ├── core/             # Componentes de infraestructura reutilizables
│   │   ├── ui.py         # Formato de consola, colores, banners y temporizadores
│   │   ├── shell.py      # Ejecución segura de subprocesos con control de timeout
│   │   ├── git.py        # Cliente encapsulado de Git y GitHub CLI
│   │   ├── runner.py     # Inversión de Dependencias: abstracción de ejecución IA
│   │   ├── parser.py     # Extracción y sanitización resiliente de JSON
│   │   └── storage.py    # Persistencia de logs y lectura de plantillas
│   └── engines/          # Abierto/Cerrado: Motores de casos de uso independientes
│       ├── doctor.py     # Diagnóstico del entorno
│       ├── pipeline.py   # Línea de montaje: Fases 1 a 7
│       ├── branch_review.py # Auditoría de diff vs rama base
│       ├── deep_audit.py # Bucle de agotamiento de un archivo (4 lentes)
│       ├── sweep.py      # Auditoría continua dual-modelo repo-wide
│       ├── convergence.py# Motor de convergencia multi-barrido con memoria y cuadrantes
│       └── self_test.py  # Auto-auditoría y contratos unitarios
├── agents/               # Prompts especializados por rol con tribunales de auto-revisión
└── logs/                 # Registros detallados con timestamps de ejecución
```


---

## 3. Patrones Arquitectónicos y de Diseño

### 3.1 Patrones Arquitectónicos
El sistema está desacoplado siguiendo una arquitectura **Modular y Orientada a Eventos** en CLI (Python), eliminando el código monolítico.
Se implementa una separación estricta en capas: Infraestructura (git, shell), Lógica (engines) y Presentación (ui).

### 3.2 Patrones de Diseño
- **Inversión de Dependencias (IoC)**: Las ejecuciones de IA (`runner.py`) están abstraídas, permitiendo inyectar modelos de forma transparente.
- **Patrón Facade**: Un único punto de entrada (`agy_pilot.py`) que enmascara la complejidad subyacente.
- **Responsabilidad Única (SRP)**: Cada motor de caso de uso (Doctor, Sweep, Pipeline) es completamente independiente y cerrado a modificaciones de otras fases.

---

## 4. Flujo de Datos y Componentes Principales
1. **Parser & CLI**: Recepción de argumentos (ticket, modelo, ramas) y validación del entorno.
2. **Motores Híbridos (Dual Model)**: El flujo `sweep` divide tareas. **Flash High** analiza y aplica código; **Claude Sonnet** actúa como fiscal (solo verificación lógica, cero código escrito).
3. **Control de Versiones Envolvente**: Todo cambio generado por la IA pasa por un staging local, tests y finalmente creación del Pull Request.

---

## 5. Consideraciones de Seguridad y Buenas Prácticas
- **Aislamiento de Prompts**: Los "agentes" o prompts viven en archivos independientes y no interactúan entre sí directamente, previniendo fuga de contexto.
- **Tribunales de Auto-revisión**: El sistema audita su propio output usando una instancia adversaria del modelo ("Abogado del diablo").
- **Timeouts Controlados**: La ejecución de subprocesos (shell) y LLM tiene barreras de tiempo estrictas para evitar cuellos de botella infinitos.

---

## 6. Despliegue e Infraestructura CI/CD
El CLI se instala a nivel de sistema mediante enlaces simbólicos (`symlinks`), permitiendo usar `agy-pilot` de forma global en cualquier proyecto del desarrollador, sin depender de entornos Docker ni integraciones complejas.
