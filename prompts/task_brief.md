# task_brief

**Propósito:** Genera un plan técnico conciso (máx. 8 líneas) para la tarea actual.
Es lo primero que lee Claude Code al abrirse — reemplaza la exploración inicial del proyecto
con pasos concretos y ordenados.

**Usado en:** `aicli/commands/task.py` → `_generate_task_brief()`
**Comando:** `ctx task`
**Modelo:** claude-sonnet-4-6
**Parámetros:** max_tokens: 512
**Versión:** 1.0

---

## Prompt

```
Sos un arquitecto de software senior. Un desarrollador va a trabajar en esta
tarea con Claude Code como asistente.

Tarea: {task_desc}
[Si se especificó archivo: Punto de entrada específico donde ocurre el problema: {file}]

Módulos del proyecto involucrados:
{listing}

Generá un plan técnico conciso de máximo 8 líneas que indique:
- Qué hay que revisar o cambiar, empezando por el archivo específico si se indicó uno
- En qué orden hacerlo
- Qué dependencias o efectos secundarios tener en cuenta

El plan va a ser la primera cosa que lea Claude Code antes de empezar. Sé específico
y técnico. Solo el plan, sin introducción ni conclusión.
```

**Formato del listing:**
```
- {m.name} ({m.file_path}): {m.description}
```

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-14 | Versión inicial | — |
