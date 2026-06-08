# AICLI — Tracker de Trabajo Diario

> **Rutina de cada sesión:**
> - **Al abrir:** escribí la fecha y tus 3 tareas en "Foco de hoy"
> - **Al cerrar:** ejecutá `/cierre` — Claude revisa el proyecto, propone qué marcar y pedí tu confirmación antes de tocar nada

---

## Progreso general

| Fase | Nombre | Estado |
|------|--------|--------|
| 0 | Entorno base | ✅ Completada |
| 1 | Typer a fondo | ✅ Completada |
| 2 | Rich — presentación | ✅ Completada |
| 3 | SQLModel y base de datos | ✅ Completada |
| 4 | Capa de servicios | ✅ Completada |
| 5 | Anthropic SDK e IA | ⬜ Pendiente |
| 6 | Comando `ctx claude` | ⬜ Pendiente |

---

## Foco de hoy

> Actualizá esto al inicio de cada sesión. Máximo 3 tareas. Si tenés más de 3, el resto va al backlog.

Fecha: <!-- actualizar -->

- [ ] <!-- tarea 1 -->
- [ ] <!-- tarea 2 -->
- [ ] <!-- tarea 3 -->

---

## Fase 0 — Entorno base

**Objetivo:** App corriendo con el primer comando funcional.

- [x] Entorno virtual creado en PyCharm
- [x] Repositorio Git inicializado y conectado a GitHub
- [x] Typer 0.26 instalado
- [x] Rich 15 instalado
- [x] Estructura de carpetas creada (`aicli/`, `commands/`, `db/`, `services/`)
- [x] `CLAUDE.md` con contexto del proyecto
- [x] `knowledge/` con decisions, patterns y progress
- [x] `.claude/commands/start.md` — comando `/project:start`
- [x] Instalar dependencias pendientes: `sqlmodel anthropic httpx python-dotenv`
- [x] Actualizar `requirements.txt` con versiones exactas (`pip freeze > requirements.txt`)
- [x] Crear `main.py` — app Typer + comando `hello` funcional
- [x] Verificar: `python main.py hello` corre sin errores

---

## Fase 1 — Typer a fondo

**Objetivo:** Entender cómo Typer construye una CLI desde type hints. Producto: `ctx status` con output hardcodeado.

- [x] Leer cómo funciona `@app.command()` como decorador
- [x] Entender Arguments vs Options vs Flags en Typer
- [x] Crear `aicli/commands/status.py` con comando `status` básico
- [x] Registrar `status` en `main.py` como sub-aplicación
- [x] Verificar: `python main.py status` corre y muestra algo

---

## Fase 2 — Rich como capa de presentación

**Objetivo:** Output visual profesional. Producto: `ctx status` con paneles y colores reales.

- [x] Entender `Console`, markup y estilos de Rich
- [x] Usar `Panel` para agrupar información en `status`
- [x] Usar `Table` para mostrar módulos documentados
- [x] Agregar `Spinner` en alguna operación que simule carga — pendiente: mover dentro de la función `status()`
- [x] Aplicar PAT-002 y PAT-003 de `knowledge/patterns.md` consistentemente

---

## Fase 3 — SQLModel y base de datos

**Objetivo:** Persistencia real. Producto: `ctx init` guarda proyecto en SQLite, `ctx status` lo lee.

- [x] Entender qué es un ORM y por qué SQLModel sobre SQLAlchemy puro
- [x] Definir modelo `Project` en `aicli/db/`
- [x] Definir modelo `Module` en `aicli/db/`
- [x] Crear conexión a SQLite en `~/.mycontext/aicli.db`
- [x] Crear tablas automáticamente al primer uso
- [x] Crear `aicli/commands/init.py` — guarda proyecto activo en la BD
- [x] Verificar: `ctx init` + `ctx status` muestran el proyecto guardado

> Decisiones de referencia: DEC-001, DEC-004, DEC-005 en `knowledge/decisions.md`

---

## Fase 4 — Capa de servicios

**Objetivo:** Separar lógica de los comandos. Producto: `indexer_service.py` detecta stack de un proyecto.

- [x] Entender el patrón Service Layer y por qué importa
- [x] Crear `aicli/services/indexer_service.py`
- [x] Implementar detección de stack por heurísticas de archivos (requirements.txt, package.json, etc.)
- [x] Conectar el servicio con `ctx init` — el comando solo llama al servicio
- [x] Verificar: el indexer detecta correctamente el stack de AICLI mismo

---

## Fase 5 — Anthropic SDK e IA real

**Objetivo:** Claude detecta módulos afectados para una tarea. Producto: `ctx task "texto"` funcional.

- [x] Configurar `ANTHROPIC_API_KEY` con `python-dotenv` (ver PAT-004)
- [x] Entender cómo funciona la API de Claude: mensajes, roles, tokens
- [ ] Crear `aicli/services/claude_service.py`
- [x] Implementar llamada básica: enviar prompt, recibir respuesta
- [x] Implementar prompt para detección de módulos afectados
- [ ] Crear `aicli/commands/task.py` — recibe texto libre, llama al servicio, muestra módulos
- [ ] Verificar: `ctx task "implementar login"` devuelve módulos relevantes

---

## Fase 6 — Comando `ctx claude`

**Objetivo:** AICLI completo end-to-end. Producto: Claude Code lanzado con contexto inyectado.

- [ ] Entender `subprocess` en Python — cómo lanzar procesos externos
- [ ] Implementar ensamblado dinámico del `CLAUDE.md` por sesión
- [ ] Crear `aicli/commands/claude_cmd.py`
- [ ] Lanzar Claude Code como subprocess con contexto pre-cargado
- [ ] Verificar: `ctx claude` abre Claude Code sin necesidad de re-explicar el proyecto

---

## Bloqueantes activos

> Registrá acá cualquier cosa que te frenó. Con fecha y contexto breve.

| Fecha | Bloqueante | Estado |
|-------|------------|--------|
| — | — | — |

---

## Log de sesiones

> Una línea por sesión. Fecha + qué avanzaste + qué dejaste pendiente.

| Fecha | Avance | Pendiente para próxima sesión |
|-------|--------|-------------------------------|
| 2026-05-30 | Setup inicial del proyecto, documentación base, TODO.md creado | Instalar dependencias, crear main.py |
| 2026-05-30 | main.py con Typer+Rich funcional, .gitignore, README, TODO.md, /cierre, fundamentos_python.md, fix encoding | Instalar 4 dependencias pendientes, actualizar requirements.txt |
| 2026-05-31 | Fase 1 completa + Fase 2 casi completa: status.py con Panel, Table, Spinner, markup Rich | Instalar 4 dependencias (Fase 0), mover spinner dentro de la función status() |
| 2026-06-06 | Instaladas 4 dependencias + PyMySQL, modelos Project y Module creados, conexión MySQL configurada con .env, tablas creadas en BD | Crear aicli/commands/init.py para guardar proyectos en la BD |
| 2026-06-06 | init.py creado con lógica de duplicados y detección de stack, decisión de no ignorar knowledge/ ni CLAUDE.md en .gitignore | Corregir bug en WHERE clause de init.py (Project.path vs proyecto.path), verificar ctx init funcionando |
| 2026-06-07 | Indexer completo con Claude API (obtener_arbol, leer_archivos_clave, analizar_con_claude, generar_contenido_modulo), ctx init guarda módulos + .md en ~/.mycontext/, fix DetachedInstanceError, fix where clause, knowledge/aprendizaje.md creado | Corregir extensión .md en archivo_md, implementar ctx status con datos reales de módulos, crear claude_service.py |
