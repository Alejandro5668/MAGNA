# Repositorio de Prompts — MAGNA

Cada prompt tiene su propio archivo. Git guarda el historial real de cambios;
el archivo agrega el contexto que git no puede dar: el **por qué** de cada modificación.

## Índice

| Prompt | Comando | Versión | Propósito |
|--------|---------|---------|-----------|
| [architecture_detect](architecture_detect.md) | `ctx init` | 1.0 | Identifica módulos de negocio reales leyendo código de carpetas nivel 1 |
| [zone_document](zone_document.md) | `ctx file` | 1.0 | Documenta en profundidad una zona/carpeta específica del proyecto |
| [file_document](file_document.md) | `ctx archive` / `ctx sync` | 1.0 | Genera o actualiza documentación de un archivo individual |
| [project_md](project_md.md) | `ctx proyecto` | 1.0 | Genera PROYECTO.md con conocimiento estructural del proyecto |
| [task_detect_modules](task_detect_modules.md) | `ctx task` | 1.0 | Detecta qué módulos son relevantes para una tarea (extended thinking) |
| [task_brief](task_brief.md) | `ctx task` | 1.0 | Genera el plan técnico antes de lanzar Claude Code |
| [sync_case_summary](sync_case_summary.md) | `ctx sync` | 1.0 | Genera mensaje Jira + memoria del caso en una sola llamada |
| [image_describe](image_describe.md) | `ctx task --imagen` / `ctx retomar` | 1.0 | Describe una imagen con precisión técnica para inyectar en contexto |

## Cómo mejorar un prompt

1. Editá el archivo del prompt
2. Actualizá el número de versión (patch: fix redacción, minor: cambio de estructura, major: reescritura)
3. Agregá una fila al **Changelog** con el cambio y el motivo
4. Commiteá: `git commit -m "prompts: <nombre> v<X.Y> — <motivo en una línea>"`
