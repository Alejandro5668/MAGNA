# Agentes de IA en MAGNA

MAGNA es un workflow de routing, no un sistema de agentes dinámico. Según la distinción de
Anthropic en "Building Effective Agents": un **workflow** encadena llamadas a un LLM por caminos
predefinidos, mientras que un **agente** decide dinámicamente sus propios pasos. Cada comando de
MAGNA dispara una secuencia fija de llamadas a IA, cada una con un rol acotado — no hace falta un
framework de orquestación porque las subtareas ya se conocen de antemano por comando. Lo que sí
vale la pena hacer es nombrar el rol de cada llamada y verificar que no haya silos de contexto
entre los pasos de una misma secuencia.

---

## Roster

| Nombre | Función | Modelo | Comando | Rol |
|---|---|---|---|---|
| El Arquitecto | `document_architecture` (indexer.py) | Sonnet | `ctx init` (1ª vez) | Identifica los módulos de negocio reales del proyecto completo, por carpeta de nivel 1. |
| El Redactor de Módulo | `generate_module_content` (indexer.py) | Sonnet | `ctx init` (re-corrida) | Re-documenta un módulo cuando su archivo fuente cambió (mtime). |
| El Especialista de Zona | `document_zone` (indexer.py) | Sonnet | `ctx file` | Documenta en profundidad una carpeta/zona puntual pedida manualmente. |
| El Documentalista de Archivo | `analyze_file_deep` (indexer.py) | Sonnet | `ctx sync` / `ctx archive` | Documenta o actualiza un archivo puntual, con o sin diff. |
| El Cronista del Proyecto | `generate_project_md` (indexer.py) | Opus | `ctx scan` | Infiere PROYECTO.md completo: identidad, convenciones, módulos, flujos críticos. |
| El Escriba de Cierre | `generate_case_summary` (indexer.py) | Haiku | `ctx sync` (cierre) | Genera mensaje Jira + pasos QA + memoria estructurada del caso, con historial de rondas previas. |
| El Perito de Imagen | `describe_image` (indexer.py) | Sonnet (visión) | `ctx task` | Describe técnicamente una imagen (manual o adjunto de Jira). |
| El Detective de Módulos | `_detect_relevant_modules` (task.py) | Sonnet + extended thinking | `ctx task` | Decide qué módulos son relevantes para la tarea. Único agente con thinking habilitado. Desde esta revisión, recibe también el contexto de PROYECTO.md. |
| El Estratega del Plan | `_generate_task_brief` (task.py) | Haiku | `ctx task` | Genera el plan técnico de 8 líneas que Claude Code lee primero. Desde esta revisión, corre después de procesar evidencia de Jira/imagen y la considera en el plan. |
| El Perito de Video | `analyze_video` (gemini.py) | Gemini 2.0 Flash | `ctx task` (Jira) | Analiza video de QA/evidencia adjunto a un ticket. |
| *(El Generador de Rol)* | no existe — referencia muerta en `MODEL_BY_OPERATION["role"]` | — | — | `rol.md` hoy es un template estático (`_ROL_DEFAULT` en `init.py`), no generado por IA. Ver OS-2 en el backlog si se retoma. |

---

## Huecos conocidos, resueltos en esta revisión

- `_generate_task_brief` (ctx task) ahora corre después de procesar imagen/adjuntos de Jira, y
  recibe un resumen de esa evidencia — antes el plan se generaba a ciegas de imágenes/video/Excel.
- `_detect_relevant_modules` (ctx task) ahora recibe el contenido de PROYECTO.md como contexto
  adicional para decidir qué módulos son relevantes — antes solo veía nombre + descripción corta.
- `ctx sync` ya no repregunta el número de ticket Jira si ya hay uno activo en la sesión — antes
  preguntaba igual aunque el dato ya estuviera disponible como default.

---

## Huecos conocidos, no resueltos (documentados, no urgentes)

- La entrada fantasma de "El Generador de Rol" en `MODEL_BY_OPERATION["role"]` no tiene función
  asociada: `rol.md` es un template estático hoy. No se elimina la entrada del modelo ni se genera
  el archivo por IA sin decisión explícita — ver OS-2.
- `document_architecture`/`document_zone` (y de forma análoga `generate_module_content`/
  `analyze_file_deep`) son familias de prompts casi idénticas con alcance distinto: una cubre el
  proyecto completo, la otra una zona puntual. No se unifican en una sola función parametrizada
  por scope porque el alcance es genuinamente distinto (principio ponytail: no abstraer sin
  duplicación real) — pero quien toque una debería saber que la otra existe.
