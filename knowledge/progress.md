# Estado del Proyecto

Última actualización: 2026-07-04

---

## Resumen ejecutivo

CLI completamente funcional y distribuida como `.exe`. Probada en proyectos reales
(PHP puro ~11.000 archivos, Next.js). Menú questionary reemplazado por TUI Textual completa
(Fase 16). Pendiente: empaquetar `.exe` nuevo y verificar Option B en compilado.

---

## Completado — Infraestructura base

- [x] Entorno virtual, repositorio Git, dependencias instaladas
- [x] Estructura de carpetas (`aicli/commands/`, `db/`, `services/`, `tui/`)
- [x] `CLAUDE.md`, `knowledge/`, `.claude/commands/start.md`
- [x] `aicli/db/models.py` — modelos `Project` y `Module` con SQLModel
- [x] `aicli/db/__init__.py` — SQLite en `~/.mycontext/ctx_bd.db`
- [x] `aicli/db/migrations.py` — migraciones de esquema
- [x] Sistema de logs en `~/.mycontext/aicli_log.log`
- [x] API key flow en primera ejecución
- [x] Selector de proyecto con menú interactivo
- [x] Loop de menú — vuelve al menú después de cada comando
- [x] `.exe` generado con PyInstaller (`ctx.spec`)

---

## Completado — TUI (Fase 16)

- [x] `aicli/tui/app.py` — TUI Textual completa: MainScreen, StatusScreen, ProjectScreen, OnboardingScreen, HelpScreen, ConfirmModal, CommandScreen (~1300 líneas)
- [x] `aicli/tui/theme.py` — paleta Noche Estrellada Van Gogh (#FFB703, #5B8DEF, #242C45, #AAB4D4, #5E6A94)
- [x] `aicli/tui/output_screen.py` — CommandOutputScreen + TuiConsole (Option B)
- [x] Vim motions: j/k navegar, g/G top/bottom, h/l colapsar/expandir
- [x] HelpScreen modal (tecla `?`) con tabla de keybindings
- [x] ConfirmModal e InputModal nativos — reemplaza questionary.confirm/text en TUI
- [x] `sync._sync_impl(ask_fn, confirm_fn)` — callbacks sustituibles desde TUI
- [x] `task._execute_task(suspend_fn)` — Claude launch desacoplado vía bridge
- [x] `ctx.spec` — `collect_submodules('textual')` + `collect_data_files('textual')`
- [x] Suite de smoke tests `tests/test_commands.py` — 23/23 pasados

---

## Completado — Comandos CLI

### `ctx init`
- [x] Detecta stack automáticamente (Python, Laravel, Next.js, PHP puro, Go, Rust, etc.)
- [x] Corre `documentar_arquitectura()` directo — sin flags, sin guía interactiva (DEC-024)
- [x] Proyecto existente: actualización incremental con señal de frescura (`last_updated_at`)
- [x] Upsert por `(project_id, file_path)` — no genera duplicados (DEC-027)
- [x] `rol.md` global creado en `~/.mycontext/rol.md` al primer init (DEC-026)

### `ctx task`
- [x] Extended thinking para detección de módulos relevantes (DEC-015)
- [x] Task brief técnico antes de lanzar Claude Code (DEC-016)
- [x] `--archivo modulo/archivo.php` ancla el contexto al archivo exacto (DEC-017)
- [x] `--imagen <ruta>` visión Claude API via base64 (DEC-032)
- [x] Captura de portapapeles Windows en `~/.mycontext/evidencias/` (DEC-049)

### `ctx file`
- [x] Documenta zona en profundidad: 1000 chars × 5 archivos, sección SQL explícita (DEC-021)
- [x] Reemplaza `ctx init --zona`

### `ctx archive`
- [x] Lee hasta 8000 chars del archivo real
- [x] Documentación profunda: funciones, queries SQL, dependencias, patrones (DEC-022, DEC-042)
- [x] Reemplaza `ctx module add`

### `ctx sync`
- [x] `git diff HEAD` + `--cached`; HEAD~1 solo como fallback (DEC-041)
- [x] Re-documenta archivos cambiados con diff + doc existente (DEC-042)
- [x] Documenta archivos nuevos automáticamente
- [x] `php -l` en archivos PHP cambiados (DEC-048)
- [x] Case card UI: Investigado / Hecho / Tener en cuenta (DEC-043, DEC-044)
- [x] Captura ticket Jira, guarda ronda con memoria estructurada (DEC-045)

### `ctx proyecto`
- [x] Genera `PROYECTO.md` con Claude a partir de árbol + módulos + muestra de código (DEC-025)
- [x] Almacenado en `~/.mycontext/projects/<id>/PROYECTO.md` — fuera de repos (DEC-029)
- [x] `builder.py` lo inyecta automáticamente en cada sesión

### `ctx retomar`
- [x] Lista tickets activos de los últimos 7 días
- [x] Muestra historial de rondas anteriores (DEC-046)
- [x] Pide motivo de reapertura + imagen + archivo, inyecta historial en sesión
- [x] `ticket_activo.json` como puente con `ctx sync` (DEC-037)

### `ctx revision`
- [x] Parsea sección 🔴 de revisión de PR pegada en terminal (DEC-047)
- [x] Extrae archivos afectados, carga historial del ticket, lanza Claude con contexto completo

### `ctx claude`
- [x] Carga contexto completo de todos los módulos del proyecto
- [x] Lanza Claude Code con `session_context.md`

### `ctx status`
- [x] Módulos agrupados por carpeta nivel 1, solo proyecto actual, fecha de última doc (DEC-038)

---

## Completado — Servicios

### `indexer.py`
- [x] Blocklist `NON_CODE_EXTENSIONS` en vez de allowlist (DEC-013)
- [x] `.gitignore` como fuente de verdad para patrones de ignorado (DEC-014)
- [x] `documentar_arquitectura()`: top 15 carpetas por densidad, max_tokens 8000 (DEC-020)
- [x] `analyze_file_deep()`: 8000 chars, actualización incremental con diff (DEC-042)
- [x] `generate_case_summary()`: JSON único con Jira + memoria del caso (DEC-043)
- [x] `describe_image()`: visión Claude API via base64 (DEC-032)
- [x] Encoding `latin-1` para lectura de archivos PHP (DEC-028)
- [x] PHP detection sin `composer.json` via `path.glob("*.php")` en raíz (DEC-031)

### `builder.py`
- [x] `build_context()`: lee `.md` de módulos relevantes y arma el contexto
- [x] Inyecta `rol.md`, `PROYECTO.md`, módulos, brief, archivo, tarea (DEC-029)

### `caller.py`
- [x] `launch_claude()`: escribe `session_context.md`, lanza Claude Code
- [x] Búsqueda automática de `claude.cmd` en rutas conocidas de Windows (DEC-019)
- [x] Inyecta historial de ticket cuando viene de `ctx retomar`

### `aicli/services/tickets.py`
- [x] Historial de tickets en `~/.mycontext/tickets.json`
- [x] Purga automática de entradas con >7 días sin actividad
- [x] `guardar_ronda()` con campo `memoria` estructurada (DEC-045)
- [x] `format_history()` compatible con rondas viejas sin campo `memoria`

### `aicli/services/activity.py`
- [x] Registro de actividad para el tab ACTIVITY de la TUI

---

## Pendiente — Validación en campo

- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec`
- [ ] Verificar Option B end-to-end (task, sync, archive, revision) en `.exe` compilado
- [ ] Verificar `ctx init` en proyecto PHP de empresa con TUI activa
- [ ] Verificar `ctx retomar` con ticket real en proyecto PHP

---

## Decisiones resueltas

Ver `knowledge/decisions.md` — DEC-001 a DEC-051.

---

## Backlog — Fase 2: Portal web

> No iniciar hasta que Fase 1 esté validada con uso real en el proyecto de la empresa.

1. Migrar BD de SQLite a MySQL/PostgreSQL para acceso multi-desarrollador
2. API REST con FastAPI (proyectos, módulos, contenido `.md`)
3. Frontend Next.js — Portal de documentación por módulos
4. Chatbot IA con RAG sobre la documentación generada
5. Sistema de roles: admin, desarrollador, consulta
